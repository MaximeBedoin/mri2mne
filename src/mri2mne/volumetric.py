"""Volumetric BEM forward and inverse -- the MNE (Windows) side of Route C.

Consumes the FreeSurfer anatomy staged by `freesurfer_bem.build_bem_anatomy`
(conformed T1, Talairach transform, closed nested BEM surfaces) and produces a
volumetric source estimate:

    build_bem_anatomy (WSL)  ->  prepare_coreg_inputs  ->  coregistration
                             ->  make_bem  ->  setup_volume_source
                             ->  make_volume_forward   ->  inverse -> -vl.stc

Everything is in the FreeSurfer *conformed* MRI (surface-RAS) frame: the scalp,
the fiducials (MNI, via Talairach), the BEM surfaces and the volume grid all
share it, so the shared `coregistration.fit_coregistration` and MNE's forward
just work. Distinct from the SimNIBS FEM surface route -- never mix a charm-frame
trans with these.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .paths import SubjectPaths


class VolumetricError(RuntimeError):
    """Raised when a volumetric BEM step cannot proceed."""


def prepare_coreg_inputs(paths: SubjectPaths, logger: logging.Logger) -> None:
    """Stage the shared coregistration inputs in the FreeSurfer MRI frame.

    Writes bem/<subject>-head.fif (the watershed outer-skin scalp) and
    bem/<subject>-fiducials.fif (MNI fiducials mapped through the subject's
    Talairach transform), after which `coregistration.fit_coregistration` runs
    unchanged -- the very same path the SimNIBS route uses.
    """
    import mne
    from mne.coreg import get_mni_fiducials
    from mne.io.constants import FIFF
    from mne.surface import complete_surface_info, read_surface

    outer_skin = paths.fs_subject_dir / "bem" / "outer_skin.surf"
    if not outer_skin.is_file():
        raise VolumetricError(
            f"Missing {outer_skin}. Run freesurfer_bem.build_bem_anatomy first."
        )

    # Scalp head surface (FreeSurfer surface RAS = MNE 'MRI' frame; mm -> m).
    rr, tris = read_surface(str(outer_skin))
    surf = {
        "rr": rr / 1000.0, "tris": tris.astype(np.int32),
        "ntri": len(tris), "np": len(rr),
        "id": FIFF.FIFFV_BEM_SURF_ID_HEAD,
        "coord_frame": FIFF.FIFFV_COORD_MRI, "sigma": 1.0,
    }
    surf = complete_surface_info(surf, copy=False, do_neighbor_vert=False)
    paths.head_surface.parent.mkdir(parents=True, exist_ok=True)
    mne.write_bem_surfaces(str(paths.head_surface), surf, overwrite=True)
    logger.info("Wrote scalp head surface (%d vertices) -> %s",
                len(rr), paths.head_surface.name)

    # MNI fiducials via the Talairach transform recon-all produced.
    try:
        fids = get_mni_fiducials(paths.subject, subjects_dir=str(paths.subjects_dir))
    except Exception as exc:  # noqa: BLE001 - many low-level readers
        raise VolumetricError(
            f"Could not derive MNI fiducials for {paths.subject}: {exc}. "
            "Needs mri/transforms/talairach.xfm and mri/orig.mgz from autorecon1."
        ) from exc
    mne.io.write_fiducials(str(paths.fiducials), fids, FIFF.FIFFV_COORD_MRI,
                           overwrite=True)
    logger.info("Wrote MNI fiducials (via Talairach) -> %s", paths.fiducials.name)


def check_bem_surfaces(paths: SubjectPaths) -> dict[str, float]:
    """Quantify watershed BEM surface quality (nesting) before building the BEM.

    `mri_watershed` can produce locally self-intersecting skull surfaces on
    atypical (e.g. large-FOV clinical) T1s, which `make_bem_model` then rejects
    with a cryptic deep error. This measures the problem up front: how many
    inner-skull vertices fall outside the outer skull, and the same for outer
    skull vs scalp. Returns a metrics dict (0 violations == clean).
    """
    import numpy as np
    from mne.surface import _points_outside_surface, complete_surface_info, read_surface

    bem = paths.fs_subject_dir / "bem"

    def _load(name):
        rr, tris = read_surface(str(bem / f"{name}.surf"))
        s = {"rr": rr / 1000.0, "tris": tris, "ntri": len(tris), "np": len(rr)}
        return rr, complete_surface_info(s, do_neighbor_tri=False)

    rr_in, inner = _load("inner_skull")
    _, outer = _load("outer_skull")
    _, skin = _load("outer_skin")
    n_in_out = int(_points_outside_surface(inner["rr"], outer, n_jobs=1).sum())
    n_out_skin = int(_points_outside_surface(outer["rr"], skin, n_jobs=1).sum())
    return {
        "bem_inner_outside_outer": float(n_in_out),
        "bem_outer_outside_skin": float(n_out_skin),
        "bem_n_vertices": float(len(rr_in)),
    }


def make_bem(
    paths: SubjectPaths,
    logger: logging.Logger,
    *,
    conductivity: tuple[float, float, float] = (0.3, 0.006, 0.3),
    ico: int | None = 4,
    strict: bool = True,
) -> "object":
    """Build and write the 3-layer BEM solution from the watershed surfaces.

    Runs `check_bem_surfaces` first: with ``strict`` (default) a self-intersecting
    watershed result raises a clear, actionable error naming the subject instead
    of failing cryptically inside MNE. Set ``strict=False`` to build anyway (the
    forward will be geometrically imperfect) for plumbing tests.
    """
    import mne

    q = check_bem_surfaces(paths)
    violations = q["bem_inner_outside_outer"] + q["bem_outer_outside_skin"]
    if violations:
        msg = (
            f"Watershed BEM surfaces for {paths.subject} self-intersect "
            f"({q['bem_inner_outside_outer']:.0f} inner-skull vertices outside "
            f"the outer skull, {q['bem_outer_outside_skin']:.0f} outer-skull "
            f"vertices outside the scalp, of {q['bem_n_vertices']:.0f}). "
            "mri_watershed struggles on atypical/large-FOV clinical T1s. Review "
            "the surfaces (QC), try a cleaner T1, or pass strict=False to build "
            "an imperfect BEM anyway."
        )
        if strict:
            raise VolumetricError(msg)
        logger.warning(msg)

    model = mne.make_bem_model(
        paths.subject, ico=ico, conductivity=conductivity,
        subjects_dir=str(paths.subjects_dir),
    )
    bem = mne.make_bem_solution(model)
    mne.write_bem_solution(str(paths.bem_solution), bem, overwrite=True)
    logger.info("Wrote 3-layer BEM solution (ico=%s) -> %s", ico,
                paths.bem_solution.name)
    return bem


def setup_volume_source(
    paths: SubjectPaths, logger: logging.Logger, *, pos_mm: float = 5.0,
) -> "object":
    """Volumetric source grid, spacing `pos_mm`, bounded by the inner skull."""
    import mne

    bem = mne.read_bem_solution(str(paths.bem_solution))
    src = mne.setup_volume_source_space(
        paths.subject, pos=pos_mm, bem=bem,
        subjects_dir=str(paths.subjects_dir), verbose="ERROR",
    )
    mne.write_source_spaces(str(paths.volume_source_space), src, overwrite=True)
    logger.info("Volume source space: %d sources @ %.1f mm -> %s",
                src[0]["nuse"], pos_mm, paths.volume_source_space.name)
    return src


def make_volume_forward(
    paths: SubjectPaths, info, trans, logger: logging.Logger,
) -> "object":
    """EEG forward on the volume grid with the 3-layer BEM."""
    import mne

    src = mne.read_source_spaces(str(paths.volume_source_space), verbose="ERROR")
    bem = mne.read_bem_solution(str(paths.bem_solution))
    fwd = mne.make_forward_solution(
        info, trans=trans, src=src, bem=bem, eeg=True, meg=False,
        verbose="ERROR",
    )
    mne.write_forward_solution(str(paths.volume_forward), fwd, overwrite=True)
    logger.info("Volume BEM forward: %d sources x %d channels -> %s",
                fwd["nsource"], fwd["nchan"], paths.volume_forward.name)
    return fwd


def make_volume_inverse(
    paths: SubjectPaths, info, noise_cov, logger: logging.Logger,
    *, loose: float = 1.0, depth: float = 0.8,
) -> "object":
    """Volumetric inverse operator (free orientation by default)."""
    import mne
    from mne.minimum_norm import make_inverse_operator, write_inverse_operator

    fwd = mne.read_forward_solution(str(paths.volume_forward), verbose="ERROR")
    inv = make_inverse_operator(info, fwd, noise_cov, loose=loose, depth=depth,
                                verbose="ERROR")
    write_inverse_operator(str(paths.volume_inverse), inv, overwrite=True,
                           verbose="ERROR")
    logger.info("Wrote volumetric inverse (loose=%.2f) -> %s", loose,
                paths.volume_inverse.name)
    return inv


def apply_volume_inverse(
    paths: SubjectPaths, evoked, inv, method: str, snr: float,
    logger: logging.Logger,
):
    """Apply the inverse and save the volume source estimate (-vl.stc)."""
    from mne.minimum_norm import apply_inverse

    lambda2 = 1.0 / float(snr) ** 2
    stc = apply_inverse(evoked, inv, lambda2, method=method, verbose="ERROR")
    stc.save(str(paths.volume_source_estimate), overwrite=True)
    logger.info("Wrote %s volume source estimate -> %s-vl.stc",
                method, paths.volume_source_estimate.name)
    return stc


def peak_location_volume(stc, src, logger: logging.Logger) -> dict[str, float]:
    """Peak vertex of a VolSourceEstimate as time + MRI-RAS coordinates (mm)."""
    vert_idx, time_idx = stc.get_peak(vert_as_index=True, time_as_index=True)
    vertno = stc.vertices[0][vert_idx]
    xyz_mm = src[0]["rr"][vertno] * 1000.0
    peak = {
        "peak_time_s": float(stc.times[time_idx]),
        "peak_mri_x_mm": float(xyz_mm[0]),
        "peak_mri_y_mm": float(xyz_mm[1]),
        "peak_mri_z_mm": float(xyz_mm[2]),
        "peak_amplitude": float(np.abs(stc.data[vert_idx, time_idx])),
    }
    logger.info("Peak source at t=%.3f s, MRI (%.1f, %.1f, %.1f) mm",
                peak["peak_time_s"], peak["peak_mri_x_mm"],
                peak["peak_mri_y_mm"], peak["peak_mri_z_mm"])
    return peak
