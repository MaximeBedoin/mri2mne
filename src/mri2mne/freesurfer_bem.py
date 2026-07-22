"""FreeSurfer head anatomy for the volumetric BEM route, driven through WSL.

The volumetric route's head model is a 3-layer BEM whose surfaces come from
FreeSurfer -- run in WSL because FreeSurfer is Linux-only, mirroring the SimNIBS
subprocess bridge.

`mri_watershed` on a raw clinical T1 gives spiky, self-intersecting skull
surfaces (large field of view, un-normalised intensities), which `make_bem_model`
rejects. So we first run `recon-all -autorecon1` (~40-60 min: conform, intensity
normalisation, skull strip, Talairach registration); watershed on that clean,
normalised brain yields the closed, nested surfaces BEM needs, and the same run
gives the Talairach transform we reuse for MNI fiducials. Everything downstream
(BEM, volume source space, coregistration, forward) then lives in the FreeSurfer
*conformed* MRI frame, so this route is self-contained and must not be mixed with
a trans from the SimNIBS/charm frame.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import wsl
from .paths import SubjectPaths

# MNE BEM surface names (what make_bem_model reads from <subject>/bem/).
_BEM_SURFACES = ("inner_skull", "outer_skull", "outer_skin")

# WSL-side FreeSurfer SUBJECTS_DIR (native ext4, fast; not /mnt/c).
_WSL_SUBJECTS_DIR = "$HOME/.mri2mne_fs/recon"


class FreeSurferError(RuntimeError):
    """Raised when a FreeSurfer step in WSL fails or produces no output."""


def build_bem_anatomy(
    paths: SubjectPaths,
    t1_nifti: str | Path,
    *,
    distro: str | None = None,
    freesurfer_home: str | None = None,
    overwrite: bool = False,
    autorecon_timeout_s: float = 10800,
    logger: logging.Logger | None = None,
) -> dict[str, Path]:
    """Run autorecon1 + watershed and stage the BEM anatomy on Windows.

    Produces, under ``subjects_dir/<subject>/``:
      * ``mri/T1.mgz`` -- conformed, normalised T1 (defines the MRI frame)
      * ``mri/transforms/talairach.xfm`` -- for MNI fiducials
      * ``bem/{inner_skull,outer_skull,outer_skin}.surf`` -- closed, nested

    Returns a dict of these Windows paths.
    """
    log = logger or logging.getLogger(__name__)
    t1_nifti = Path(t1_nifti)
    if not t1_nifti.is_file():
        raise FreeSurferError(f"T1 not found: {t1_nifti}")

    mri_dir = paths.fs_subject_dir / "mri"
    xfm_dir = mri_dir / "transforms"
    bem_dir = paths.fs_subject_dir / "bem"
    out = {
        "t1_mgz": mri_dir / "T1.mgz",
        # orig.mgz is needed alongside talairach.xfm for MNI fiducials.
        "orig_mgz": mri_dir / "orig.mgz",
        "talairach_xfm": xfm_dir / "talairach.xfm",
        **{n: bem_dir / f"{n}.surf" for n in _BEM_SURFACES},
    }
    if not overwrite and all(p.exists() for p in out.values()):
        log.info("FreeSurfer BEM anatomy already present for %s", paths.subject)
        return out

    subj = paths.subject
    sd = _WSL_SUBJECTS_DIR
    t1_wsl = wsl.to_wsl_path(t1_nifti)

    # --- 1. autorecon1: conform + normalise + skull strip + Talairach --------
    log.info("recon-all -autorecon1 for %s (WSL, ~40-60 min)", subj)
    recon = (
        f"export SUBJECTS_DIR={sd}; mkdir -p {sd}; "
        + (f"rm -rf {sd}/{subj}; " if overwrite else "")
        + f'recon-all -s {subj} -i "{t1_wsl}" -autorecon1 -sd {sd} && echo RECON_OK'
    )
    res = wsl.run_freesurfer(
        recon, freesurfer_home=freesurfer_home, distro=distro,
        check=False, timeout=autorecon_timeout_s, logger=log,
    )
    if "RECON_OK" not in res.stdout:
        raise FreeSurferError(
            "recon-all -autorecon1 failed.\n"
            f"stdout tail: {res.stdout.strip()[-600:]}\n"
            f"stderr tail: {res.stderr.strip()[-400:]}"
        )

    # --- 2. watershed on the normalised brain --------------------------------
    log.info("mri_watershed on the normalised T1 for %s (WSL)", subj)
    ws = (
        f"export SUBJECTS_DIR={sd}; S={sd}/{subj}; "
        f"mkdir -p $S/bem/watershed; "
        f"mri_watershed -useSRAS -surf $S/bem/watershed/{subj} "
        f"$S/mri/T1.mgz $S/bem/watershed/ws.mgz >/dev/null 2>&1; "
        f"for s in inner_skull outer_skull outer_skin; do "
        f'test -f $S/bem/watershed/{subj}_${{s}}_surface || {{ echo MISSING_$s; exit 3; }}; '
        f"done; echo WS_OK"
    )
    res = wsl.run_freesurfer(
        ws, freesurfer_home=freesurfer_home, distro=distro,
        check=False, timeout=1800, logger=log,
    )
    if "WS_OK" not in res.stdout:
        raise FreeSurferError(
            "mri_watershed did not produce the expected surfaces.\n"
            f"stdout: {res.stdout.strip()[-400:]}\nstderr: {res.stderr.strip()[-400:]}"
        )

    # --- 3. copy the results back to the Windows subject layout --------------
    for d in (mri_dir, xfm_dir, bem_dir):
        d.mkdir(parents=True, exist_ok=True)
    copies = {
        f"{sd}/{subj}/mri/T1.mgz": out["t1_mgz"],
        f"{sd}/{subj}/mri/orig.mgz": out["orig_mgz"],
        f"{sd}/{subj}/mri/transforms/talairach.xfm": out["talairach_xfm"],
        **{
            f"{sd}/{subj}/bem/watershed/{subj}_{n}_surface": out[n]
            for n in _BEM_SURFACES
        },
    }
    for src_wsl, dst_win in copies.items():
        _copy_from_wsl(src_wsl, dst_win, distro=distro, logger=log)
        if not dst_win.is_file():
            raise FreeSurferError(f"Copy-back failed: {dst_win}")

    log.info("FreeSurfer BEM anatomy ready for %s -> %s", subj, paths.fs_subject_dir)
    return out


def _copy_from_wsl(
    src_wsl: str, dst_win: Path, *, distro: str | None, logger: logging.Logger
) -> None:
    """Copy one file out of WSL to a Windows path via `cp` to /mnt/<drive>."""
    dst_wsl = wsl.to_wsl_path(dst_win)
    parent = wsl.to_wsl_path(dst_win.parent)
    wsl.run(
        f'mkdir -p "{parent}" && cp "{src_wsl}" "{dst_wsl}"',
        distro=distro, check=True, timeout=300, logger=logger,
    )
