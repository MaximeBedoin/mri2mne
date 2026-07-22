"""SimNIBS `charm` wrapper: the one heavy step in the pipeline.

`charm` runs deep-learning segmentation, meshing and surface extraction in
roughly 1-2 h per subject on CPU. It is a console script rather than a python
API, and it writes `m2m_<subID>` into the *current working directory*, so we
drive it via subprocess with an explicit cwd.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


class HeadModelError(RuntimeError):
    """Raised when charm fails or produces an incomplete head model."""


def find_charm(bin_dir: Path | None) -> str:
    """Locate the charm executable, preferring an explicitly configured dir."""
    if bin_dir is not None:
        # Windows ships charm.cmd; other platforms a bare script.
        for name in ("charm.cmd", "charm.exe", "charm.bat", "charm"):
            candidate = bin_dir / name
            if candidate.is_file():
                return str(candidate)
        raise HeadModelError(
            f"simnibs.bin_dir is set to {bin_dir} but contains no charm "
            "executable. Point it at the 'bin' folder of your SimNIBS install."
        )

    found = shutil.which("charm")
    if found:
        return found
    raise HeadModelError(
        "charm not found on PATH and simnibs.bin_dir is not set. Install "
        "SimNIBS 4 (https://simnibs.github.io) and set simnibs.bin_dir in "
        "config.yaml to its bin folder."
    )


def _needs_forcesform(t1: Path, logger: logging.Logger) -> bool:
    """True when the T1's qform is unset but a usable sform is present.

    charm reads geometry from the qform by default and aborts if qform_code is
    0; passing --forcesform makes it use the sform instead. We only add the flag
    when it is actually needed and safe (sform_code > 0).
    """
    try:
        import nibabel as nib

        header = nib.load(str(t1)).header
        qform_code = int(header["qform_code"])
        sform_code = int(header["sform_code"])
    except Exception as exc:  # noqa: BLE001 - never let a header probe block charm
        logger.warning("Could not inspect T1 header (%s); leaving charm flags as-is", exc)
        return False

    if qform_code == 0 and sform_code > 0:
        logger.info("T1 qform_code is 0 but sform is valid; adding --forcesform")
        return True
    if qform_code == 0 and sform_code == 0:
        logger.warning(
            "T1 has neither qform nor sform set; charm will likely fail. Check "
            "the conversion of %s", t1.name,
        )
    return False


def _validate_outputs(m2m_dir: Path) -> None:
    """Confirm charm produced the artefacts the rest of the pipeline needs."""
    required = {
        "final_tissues.nii.gz": "tissue segmentation",
        "final_tissues_LUT.txt": "tissue label lookup table",
    }
    missing = [
        f"{name} ({what})"
        for name, what in required.items()
        if not (m2m_dir / name).is_file()
    ]
    if missing:
        raise HeadModelError(
            f"charm finished but {m2m_dir} is missing: {', '.join(missing)}. "
            "Inspect the charm report in that folder."
        )


def run_charm(
    subject: str,
    t1: Path,
    work_dir: Path,
    m2m_dir: Path,
    charm_exe: str,
    logger: logging.Logger,
    t2: Path | None = None,
    extra_args: list[str] | None = None,
    timeout_s: int = 21600,
    force: bool = False,
    n_threads: int = 1,
) -> Path:
    """Build the SimNIBS head model for one subject.

    `work_dir` is used as charm's cwd, so `m2m_<subject>` lands beside the
    other derivatives rather than wherever the batch was launched from.
    """
    if not t1.is_file():
        raise HeadModelError(f"T1 not found: {t1}")

    if m2m_dir.exists() and force:
        logger.info("Removing existing head model at %s (forced re-run)", m2m_dir)
        shutil.rmtree(m2m_dir)

    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [charm_exe, subject, str(t1)]
    if t2 is not None:
        if t2.is_file():
            cmd.append(str(t2))
            logger.info("Using T2 %s for improved skull segmentation", t2.name)
        else:
            logger.warning("Configured T2 not found (%s); continuing T1-only", t2)
    if force:
        cmd.append("--forcerun")

    # charm rejects a NIfTI whose qform_code is 0 unless told to fall back on
    # the sform. Converters vary -- dcm2niix sets both, but a nibabel-written or
    # dicom2nifti T1 sometimes leaves qform unset -- so detect it and add the
    # documented escape hatch rather than failing at minute zero.
    if _needs_forcesform(t1, logger) and "--forcesform" not in (extra_args or []):
        cmd.append("--forcesform")

    cmd.extend(extra_args or [])

    logger.info("Starting charm (expect 1-2 h). Command: %s", " ".join(cmd))
    start = time.monotonic()

    # SimNIBS spawns its own threaded workers. Left unset, every parallel
    # subject grabs all cores and they thrash; pinned to 1, most of the machine
    # sits idle during the pipeline's dominant step. The batch runner divides
    # the cores among workers and passes the share in here.
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(n_threads)
    env["MKL_NUM_THREADS"] = str(n_threads)
    env["OPENBLAS_NUM_THREADS"] = str(n_threads)
    logger.info("Allotting %d thread(s) to charm", n_threads)

    log_path = m2m_dir.parent / f"charm_{subject}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log_fh:
            proc = subprocess.run(
                cmd,
                cwd=str(work_dir),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
                # charm.cmd is a batch wrapper, so Windows needs the shell
                # resolution that shell=False + explicit .cmd path still gives us.
                shell=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise HeadModelError(
            f"charm exceeded the {timeout_s}s timeout for {subject}. Raise "
            "simnibs.timeout_s or reduce run.n_jobs if the machine is swapping."
        ) from exc
    except FileNotFoundError as exc:
        raise HeadModelError(
            f"Could not execute charm at {charm_exe}: {exc}"
        ) from exc

    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        tail = ""
        if log_path.is_file():
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
        raise HeadModelError(
            f"charm failed for {subject} with exit code {proc.returncode} after "
            f"{elapsed / 60:.1f} min. Last lines of {log_path}:\n{tail}"
        )

    produced = work_dir / f"m2m_{subject}"
    if produced != m2m_dir:
        if m2m_dir.exists():
            shutil.rmtree(m2m_dir)
        shutil.move(str(produced), str(m2m_dir))

    _validate_outputs(m2m_dir)
    logger.info("charm completed in %.1f min -> %s", elapsed / 60, m2m_dir)
    return m2m_dir


def _find_mni_tool(bin_dir: Path | None) -> str | None:
    """Locate the mni2subject_coords executable, if available."""
    names = ("mni2subject_coords.exe", "mni2subject_coords.cmd", "mni2subject_coords")
    if bin_dir is not None:
        for name in names:
            cand = bin_dir / name
            if cand.is_file():
                return str(cand)
    found = shutil.which("mni2subject_coords")
    return found


def mni_to_subject(
    coords_mni,
    m2m_dir: Path,
    logger: logging.Logger,
    bin_dir: Path | None = None,
):
    """Map MNI152 coordinates (mm) into subject space using charm's warp.

    Preferred route is the `mni2subject_coords` executable via subprocess -- it
    uses SimNIBS' own Python, so the pipeline itself never needs `import
    simnibs`, which matters because SimNIBS ships a separate distribution. Falls
    back to an in-process import when the tool is not found. Raises
    `HeadModelError` if neither is available.
    """
    import numpy as np

    coords = np.atleast_2d(np.asarray(coords_mni, dtype=float))

    exe = _find_mni_tool(bin_dir)
    if exe is not None:
        result = _mni_to_subject_subprocess(exe, coords, m2m_dir, logger)
        if result is not None:
            logger.info("Warped %d MNI coord(s) via %s", len(result), Path(exe).name)
            return result

    try:
        from simnibs import mni2subject_coords
    except Exception as exc:  # noqa: BLE001 - ImportError or numpy-ABI ValueError
        raise HeadModelError(
            "MNI->subject fiducials need either the `mni2subject_coords` "
            "executable (set simnibs.bin_dir to your SimNIBS bin folder) or an "
            "importable `simnibs` package; neither is available "
            f"({type(exc).__name__}). Alternatively place a manually created "
            "<subject>-fiducials.fif in the subject's bem folder."
        ) from exc

    subject_coords = np.atleast_2d(
        np.asarray(mni2subject_coords(coords.tolist(), str(m2m_dir)), dtype=float)
    )
    logger.info("Warped %d MNI coord(s) via in-process simnibs", len(subject_coords))
    return subject_coords


def _mni_to_subject_subprocess(exe: str, coords, m2m_dir: Path, logger):
    """Run mni2subject_coords over a CSV. Returns None on any failure so the
    caller can fall back to the in-process route."""
    import csv
    import tempfile

    import numpy as np

    tmp = Path(tempfile.mkdtemp(prefix="mri2mne_mni_"))
    in_csv, out_csv = tmp / "mni.csv", tmp / "subject.csv"
    # 'Generic' rows are transported as-is (not projected to skin), which is
    # what we want: these coordinates only initialise ICP.
    with open(in_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for i, (x, y, z) in enumerate(coords):
            writer.writerow(["Generic", x, y, z, f"p{i}"])

    cmd = [exe, "-m", str(m2m_dir), "-s", str(in_csv), "-o", str(out_csv),
           "-t", "nonl"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not out_csv.is_file():
        logger.warning(
            "mni2subject_coords failed (rc=%d); falling back. stderr: %s",
            proc.returncode, (proc.stderr or "").strip()[:300],
        )
        return None

    out = []
    with open(out_csv, "r", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 4 and row[0].strip().lower() == "generic":
                out.append([float(row[1]), float(row[2]), float(row[3])])
    if len(out) != len(coords):
        logger.warning("mni2subject_coords returned %d of %d coords; falling back",
                       len(out), len(coords))
        return None
    return np.asarray(out, dtype=float)
