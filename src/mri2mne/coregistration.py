"""Read the electrode digitisation and fit the head-to-MRI transform.

With digitised electrodes this is the step that actually determines source
localisation accuracy -- far more than the forward-model details -- so the
residual is measured, recorded and used to flag subjects, never assumed good.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .paths import SubjectPaths


class CoregistrationError(RuntimeError):
    """Raised when digitisation cannot be read or the fit is unusable."""


def read_digitisation(path: Path, logger: logging.Logger):
    """Load a digitisation file into an MNE `DigMontage`.

    Dispatches on extension across the formats MNE supports; `.fif` may be
    either a raw recording carrying dig points or a standalone montage.
    """
    import mne

    if not path.is_file():
        raise CoregistrationError(
            f"Digitisation file not found: {path}. Check paths.digitisation in "
            "config.yaml."
        )

    suffix = path.suffix.lower()
    logger.info("Reading digitisation %s", path.name)

    try:
        if suffix == ".fif":
            try:
                return mne.channels.read_dig_fif(str(path))
            except Exception:  # noqa: BLE001 - fall back to raw-with-dig
                raw = mne.io.read_raw_fif(str(path), preload=False, verbose="ERROR")
                montage = raw.get_montage()
                if montage is None:
                    raise CoregistrationError(
                        f"{path} contains no digitisation points."
                    )
                return montage
        if suffix in (".hsp", ".elp", ".eeg"):
            return mne.channels.read_dig_polhemus_isotrak(str(path))
        if suffix == ".bvct":
            return mne.channels.read_dig_captrak(str(path))
        if suffix == ".hpts":
            return mne.channels.read_dig_hpts(str(path))
        if suffix in (".sfp", ".elc", ".csd", ".txt", ".bvef", ".xyz"):
            return mne.channels.read_custom_montage(str(path))
    except CoregistrationError:
        raise
    except Exception as exc:  # noqa: BLE001 - readers raise many types
        raise CoregistrationError(f"Failed to read {path}: {exc}") from exc

    raise CoregistrationError(
        f"Unsupported digitisation format '{suffix}' for {path}. Supported: "
        ".fif .hsp .elp .bvct .hpts .sfp .elc .csd .xyz"
    )


def build_info(montage, logger: logging.Logger):
    """Wrap a montage in a minimal EEG `Info`, which is what coreg consumes."""
    import mne

    ch_names = [
        name for name in montage.ch_names
        if name.lower() not in ("lpa", "nasion", "rpa", "nz")
    ]
    if not ch_names:
        raise CoregistrationError(
            "The digitisation contains fiducials but no electrode positions."
        )

    info = mne.create_info(ch_names, sfreq=1000.0, ch_types="eeg")
    try:
        # Raise rather than ignore: an electrode without a position cannot
        # contribute to the forward model, and dropping it silently would
        # change the montage behind the user's back.
        info.set_montage(montage, on_missing="raise")
    except ValueError as exc:
        raise CoregistrationError(
            f"Could not attach the digitisation to an EEG montage: {exc}\n"
            "Common causes: electrode labels differing between the "
            "digitisation and the recording, or fiducials stored as ordinary "
            "channels."
        ) from exc

    logger.info("Digitisation carries %d electrodes", len(ch_names))
    return info


def fit_coregistration(
    paths: SubjectPaths,
    info,
    icp_iterations: int,
    omit_distance_mm: float,
    logger: logging.Logger,
) -> tuple[Path, dict[str, float]]:
    """Fit head->MRI by fiducials, then refine with ICP on the head shape."""
    import mne
    from mne.coreg import Coregistration

    # Read the fiducials ourselves and hand over the point list. Passing a bare
    # path worked in older MNE but 1.12+ only accepts "auto"/"estimated", a
    # dict, or a list of dig points -- a path string trips an internal assert.
    fid_points, _ = mne.io.read_fiducials(str(paths.fiducials))

    # scale_mode is left at its default ("none"): with real subject anatomy the
    # MRI must never be rescaled to fit the head shape. It also stopped being a
    # constructor argument in newer MNE, so we rely on the default.
    coreg = Coregistration(
        info,
        subject=paths.subject,
        subjects_dir=str(paths.subjects_dir),
        fiducials=fid_points,
    )

    coreg.fit_fiducials(verbose="ERROR")
    initial = _residual_mm(coreg)
    logger.info("After fiducial alignment: median residual %.2f mm", initial["median"])

    # Coarse ICP *before* discarding outliers. Judging a point's distance to the
    # scalp from a fiducial-only alignment throws away good points whenever the
    # fiducials are slightly off -- which, with automatically placed fiducials,
    # is the normal case rather than the exception.
    coreg.fit_icp(n_iterations=6, verbose="ERROR")
    coarse = _residual_mm(coreg)
    logger.info("After coarse ICP: median residual %.2f mm", coarse["median"])

    n_before = _n_active_points(coreg)
    coreg.omit_head_shape_points(distance=omit_distance_mm / 1000.0)
    n_omitted = max(0, n_before - _n_active_points(coreg))
    if n_omitted:
        logger.info("Omitted %d digitised point(s) beyond %.1f mm from the scalp",
                    n_omitted, omit_distance_mm)

    coreg.fit_icp(n_iterations=icp_iterations, verbose="ERROR")
    final = _residual_mm(coreg)
    logger.info(
        "After ICP (%d iterations): median %.2f mm, 95th pct %.2f mm, max %.2f mm",
        icp_iterations, final["median"], final["p95"], final["max"],
    )

    paths.trans.parent.mkdir(parents=True, exist_ok=True)
    mne.write_trans(str(paths.trans), coreg.trans, overwrite=True)
    logger.info("Wrote %s", paths.trans)

    metrics = {
        "coreg_residual_median_mm": final["median"],
        "coreg_residual_p95_mm": final["p95"],
        "coreg_residual_max_mm": final["max"],
        "coreg_residual_initial_median_mm": initial["median"],
        "coreg_residual_coarse_median_mm": coarse["median"],
        "coreg_n_points_omitted": float(n_omitted),
    }
    return paths.trans, metrics


def _n_active_points(coreg) -> int:
    """Count head-shape points still in play.

    Read via the public distance computation rather than Coregistration's
    private filter attribute, whose name has moved between MNE versions.
    """
    try:
        return int(np.asarray(coreg.compute_dig_mri_distances()).size)
    except Exception:  # noqa: BLE001 - diagnostic only, never fail the fit
        return 0


def _residual_mm(coreg) -> dict[str, float]:
    """Summarise digitised-point to scalp distances, in millimetres."""
    distances = np.asarray(coreg.compute_dig_mri_distances(), dtype=float) * 1000.0
    if distances.size == 0:
        return {"median": float("nan"), "p95": float("nan"), "max": float("nan")}
    return {
        "median": float(np.median(distances)),
        "p95": float(np.percentile(distances, 95)),
        "max": float(distances.max()),
    }
