"""Inverse operator and source estimates -- the actual source analysis.

Combines the SimNIBS FEM forward, the noise covariance and the EEG data into a
distributed inverse solution over the cortical surface source space. Minimum-norm
family (MNE / dSPM / sLORETA / eLORETA), all standard MNE-Python and citable; an
LCMV beamformer is the natural alternative and is noted in the README.
"""

from __future__ import annotations

import logging

import numpy as np

from .paths import SubjectPaths

_INVERSE_METHODS = ("MNE", "dSPM", "sLORETA", "eLORETA")


class InverseError(RuntimeError):
    """Raised when the inverse operator or source estimate cannot be built."""


def make_inverse(
    paths: SubjectPaths,
    info,
    noise_cov,
    logger: logging.Logger,
    loose: float = 0.2,
    depth: float = 0.8,
):
    """Build and save the inverse operator.

    `loose=0.2` is the standard loose-orientation constraint for a cortical
    surface source space: dipoles are biased toward the surface normal but not
    fixed to it. (A volume grid would instead use loose=1.0, free orientation.)
    """
    import mne
    from mne.minimum_norm import make_inverse_operator, write_inverse_operator

    fwd = mne.read_forward_solution(str(paths.forward), verbose="ERROR")

    # A surface source space carries per-source normals and supports loose
    # orientation; a volume one does not, so fall back to free orientation.
    is_surface = all(s["type"] == "surf" for s in fwd["src"])
    if not is_surface:
        loose = 1.0

    try:
        inv = make_inverse_operator(
            info, fwd, noise_cov, loose=loose, depth=depth, verbose="ERROR",
        )
    except Exception as exc:  # noqa: BLE001
        raise InverseError(
            f"Could not build the inverse operator: {exc}. A common cause is a "
            "mismatch between the EEG channels and the forward model's channels."
        ) from exc

    paths.inverse.parent.mkdir(parents=True, exist_ok=True)
    write_inverse_operator(str(paths.inverse), inv, verbose="ERROR")
    logger.info("Wrote inverse operator (loose=%.2f) -> %s", loose, paths.inverse)
    return inv


def apply_inverse_evoked(
    paths: SubjectPaths,
    evoked,
    inv,
    method: str,
    snr: float,
    logger: logging.Logger,
):
    """Apply the inverse to an Evoked, producing a source estimate.

    For the cortical source space this is a surface `SourceEstimate`, saved as
    `<subject>-lh.stc` / `<subject>-rh.stc`.
    """
    import mne  # noqa: F401  (ensures the stc classes are registered)
    from mne.minimum_norm import apply_inverse

    if method not in _INVERSE_METHODS:
        raise InverseError(
            f"Unknown inverse method '{method}'. Choose from {_INVERSE_METHODS}."
        )

    lambda2 = 1.0 / snr ** 2
    stc = apply_inverse(evoked, inv, lambda2=lambda2, method=method,
                        verbose="ERROR")

    paths.source_estimate.parent.mkdir(parents=True, exist_ok=True)
    stc.save(str(paths.source_estimate), overwrite=True, verbose="ERROR")
    logger.info("Wrote %s source estimate -> %s-[lh|rh].stc",
                method, paths.source_estimate.name)

    if not np.all(np.isfinite(stc.data)):
        raise InverseError("Source estimate contains non-finite values.")
    return stc


def peak_location(stc, src, logger: logging.Logger) -> dict[str, float]:
    """Locate the strongest source, in mesh-world (MRI) millimetres.

    Works for a surface estimate (lh+rh) and for a volume estimate. For clinical
    localisation this peak, not the whole map, is usually the deliverable.
    """
    vert_idx, t_peak = stc.get_peak(vert_as_index=True, time_as_index=False)

    # Positions of the in-use sources, concatenated across source spaces in the
    # same order stc stacks them (lh then rh for a surface estimate).
    rr = np.concatenate([s["rr"][s["vertno"]] for s in src], axis=0)
    peak_mm = rr[vert_idx] * 1000.0
    amplitude = float(np.abs(stc.data[vert_idx]).max())

    n_lh = int(src[0]["nuse"]) if len(src) > 1 else None
    hemi = "?" if n_lh is None else ("lh" if vert_idx < n_lh else "rh")

    logger.info(
        "Peak source at t=%.3f s, hemi=%s, MRI (%.1f, %.1f, %.1f) mm, amp %.3g",
        t_peak, hemi, *peak_mm, amplitude,
    )
    return {
        "peak_time_s": float(t_peak),
        "peak_hemi": hemi,
        "peak_mri_x_mm": float(peak_mm[0]),
        "peak_mri_y_mm": float(peak_mm[1]),
        "peak_mri_z_mm": float(peak_mm[2]),
        "peak_amplitude": amplitude,
    }
