"""Coregistration inputs from the SimNIBS head model (pipeline side).

Drives `_simnibs_mesh_helper.py` (which runs in SimNIBS' Python) to pull the
scalp surface and subject-space fiducials out of the head model, then writes
them as the FreeSurfer-style files MNE's coregistration expects. Everything is
in mesh-world coordinates, which SimNIBS treats as MNE's "MRI" frame.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from .paths import SubjectPaths
from .simnibs_forward import ForwardError, simnibs_python


def extract_coreg_inputs(
    paths: SubjectPaths,
    bin_dir: Path | None,
    logger: logging.Logger,
    timeout_s: int = 1800,
) -> dict[str, list[float]]:
    """Write bem/<subject>-head.fif and -fiducials.fif from the SimNIBS mesh.

    Returns the fiducial dictionary (mesh-world mm). The head surface is the
    SimNIBS skin surface; the fiducials are the ones charm warped into subject
    space. Reuses MNE's coregistration downstream, unchanged.
    """
    import mne
    from mne.io.constants import FIFF
    from mne.surface import complete_surface_info

    py = simnibs_python(bin_dir)
    scalp_npz = paths.root / "coreg" / "scalp.npz"
    fids_json = paths.root / "coreg" / "fiducials.json"
    scalp_npz.parent.mkdir(parents=True, exist_ok=True)

    cfg = {
        "m2m_dir": str(paths.m2m_dir),
        "out_scalp_npz": str(scalp_npz),
        "out_fiducials_json": str(fids_json),
    }
    cfg_path = paths.root / "coreg" / "mesh_config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    helper = Path(__file__).with_name("_simnibs_mesh_helper.py")
    proc = subprocess.run(
        [str(py), str(helper), str(cfg_path)],
        capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    if proc.returncode != 0 or not scalp_npz.is_file():
        tail = "\n".join((proc.stderr or "").splitlines()[-12:])
        raise ForwardError(
            f"SimNIBS mesh extraction failed (exit {proc.returncode}):\n{tail}"
        )

    # --- Head surface -> bem/<subject>-head.fif (mesh world = MRI, metres) --
    data = np.load(scalp_npz)
    rr = np.asarray(data["rr_mm"], dtype=float) / 1000.0
    tris = np.asarray(data["tris"], dtype=np.int32)
    surf = {
        "rr": rr, "tris": tris, "ntri": len(tris), "np": len(rr),
        "id": FIFF.FIFFV_BEM_SURF_ID_HEAD,
        "coord_frame": FIFF.FIFFV_COORD_MRI, "sigma": 1.0,
    }
    surf = complete_surface_info(surf, copy=False, do_neighbor_vert=False)
    paths.head_surface.parent.mkdir(parents=True, exist_ok=True)
    mne.write_bem_surfaces(str(paths.head_surface), surf, overwrite=True)
    logger.info("Wrote scalp head surface (%d vertices) -> %s",
                len(rr), paths.head_surface.name)

    # --- Fiducials -> bem/<subject>-fiducials.fif ---------------------------
    fids = json.loads(fids_json.read_text(encoding="utf-8"))
    missing = {"lpa", "nasion", "rpa"} - set(fids)
    if missing:
        raise ForwardError(
            f"charm did not provide fiducials {sorted(missing)}; expected them "
            f"in {paths.m2m_dir}/eeg_positions/Fiducials.csv"
        )
    idents = {
        "lpa": FIFF.FIFFV_POINT_LPA,
        "nasion": FIFF.FIFFV_POINT_NASION,
        "rpa": FIFF.FIFFV_POINT_RPA,
    }
    pts = [
        {
            "r": np.asarray(fids[k], dtype=float) / 1000.0,
            "ident": idents[k], "kind": FIFF.FIFFV_POINT_CARDINAL,
            "coord_frame": FIFF.FIFFV_COORD_MRI,
        }
        for k in ("lpa", "nasion", "rpa")
    ]
    mne.io.write_fiducials(str(paths.fiducials), pts, FIFF.FIFFV_COORD_MRI,
                           overwrite=True)
    logger.info("Wrote subject fiducials (from charm) -> %s", paths.fiducials.name)
    return fids
