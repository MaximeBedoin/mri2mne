"""FEM EEG forward via SimNIBS, driven from the pipeline environment.

This is the pipeline-side (irm2mne) half. It prepares the inputs, then hands
off to `_simnibs_fem_helper.py`, which runs inside SimNIBS' own Python because
the leadfield solver and its MNE bridge live only there. The helper writes a
`-fwd.fif`; we read it back here.

Coordinate frames: SimNIBS treats the mesh world (subject scanner RAS) as MNE's
"MRI" frame. The coregistration therefore produces a head->mesh-world trans,
and the leadfield electrodes are the digitised electrodes mapped into mesh world
with that trans. `make_forward` (in the helper) uses the same trans + info to
express the forward in head coordinates.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from .paths import SubjectPaths


class ForwardError(RuntimeError):
    """Raised when the FEM forward cannot be produced."""


def simnibs_python(bin_dir: Path | None) -> Path:
    """Locate the Python interpreter of the SimNIBS environment.

    The leadfield + MNE bridge must run there. `bin_dir` is the SimNIBS Scripts
    folder (holds charm); its interpreter sits one level up.
    """
    if bin_dir is None:
        raise ForwardError(
            "simnibs.bin_dir must be set for the FEM forward: it locates the "
            "SimNIBS Python that runs the leadfield solver."
        )
    candidate = bin_dir.parent / "python.exe"
    if not candidate.is_file():
        candidate = bin_dir.parent / "bin" / "python"  # non-Windows layout
    if not candidate.is_file():
        raise ForwardError(
            f"Could not find the SimNIBS Python next to {bin_dir} (looked for "
            f"{candidate}). Point simnibs.bin_dir at the env's Scripts folder."
        )
    return candidate


def make_fem_forward(
    paths: SubjectPaths,
    info,
    trans,
    bin_dir: Path | None,
    logger: logging.Logger,
    subsampling: int | None = 10000,
    cpus: int = 1,
    morph_to_fsaverage: int | None = 5,
    timeout_s: int = 21600,
) -> tuple[Path, dict[str, float]]:
    """Run the SimNIBS FEM leadfield and convert it to an MNE forward.

    Returns (forward_path, metrics). The forward and its cortical source space
    are written to the subject's mne directory.
    """
    import mne

    import sys

    py = simnibs_python(bin_dir)

    # SimNIBS' leadfield parallelisation passes a local closure to a
    # multiprocessing pool, which Windows (spawn start method) cannot pickle
    # ("Can't pickle local object TDCSLEADFIELD.run.<locals>.post"). Force a
    # single process there; the FEM solve is serial but correct.
    if sys.platform == "win32" and cpus != 1:
        logger.warning("SimNIBS leadfield cannot use cpus>1 on Windows; using 1")
        cpus = 1

    # Persist info and trans for the helper (which runs in the other env, where
    # SimNIBS' prepare_montage maps the electrodes into subject space).
    info_fif = paths.mne_dir / f"{paths.subject}-fem-info.fif"
    trans_fif = paths.trans
    paths.mne_dir.mkdir(parents=True, exist_ok=True)
    mne.io.write_info(str(info_fif), info)
    ch_names = [info["ch_names"][i] for i in mne.pick_types(info, eeg=True, exclude=[])]
    montage_csv = paths.mne_dir / f"{paths.subject}-montage.csv"

    cfg = {
        "m2m_dir": str(paths.m2m_dir),
        "fem_dir": str(paths.root / "fem"),
        "montage_csv": str(montage_csv),
        "info_fif": str(info_fif),
        "trans_fif": str(trans_fif),
        "out_fwd": str(paths.forward),
        "out_src": str(paths.source_space),
        "out_morph": str(paths.mne_dir / f"{paths.subject}-morph.h5"),
        "subsampling": subsampling,
        "cpus": int(cpus),
        "morph_to_fsaverage": morph_to_fsaverage,
    }
    cfg_path = paths.root / "fem_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    helper = Path(__file__).with_name("_simnibs_fem_helper.py")
    logger.info("Running FEM leadfield via SimNIBS Python (this is slow)")
    proc = subprocess.run(
        [str(py), "-u", str(helper), str(cfg_path)],
        capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    log_path = paths.root / "logs" / f"{paths.subject}_fem.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text((proc.stdout or "") + "\n---STDERR---\n" + (proc.stderr or ""),
                        encoding="utf-8")

    if proc.returncode != 0 or not paths.forward.is_file():
        tail = "\n".join((proc.stdout or "").splitlines()[-5:] +
                         (proc.stderr or "").splitlines()[-15:])
        raise ForwardError(
            f"SimNIBS FEM forward failed (exit {proc.returncode}). See "
            f"{log_path}. Tail:\n{tail}"
        )

    result = _parse_result(proc.stdout)
    logger.info("FEM forward: %s sources x %s channels (%s source space)",
                result.get("n_sources"), result.get("n_channels"),
                result.get("src_type"))

    # Re-read to confirm the cross-environment handoff and channel consistency.
    fwd = mne.read_forward_solution(str(paths.forward), verbose="ERROR")
    if fwd["info"]["ch_names"] != ch_names:
        logger.warning("Forward channel order differs from the montage order")

    metrics = {
        "fwd_n_sources": float(fwd["nsource"]),
        "fwd_n_channels": float(fwd["nchan"]),
        "fwd_source_type": 1.0 if result.get("src_type") == "surf" else 0.0,
    }
    return paths.forward, metrics


def _parse_result(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith("MRI2MNE_RESULT "):
            try:
                return json.loads(line[len("MRI2MNE_RESULT "):])
            except json.JSONDecodeError:
                return {}
    return {}
