"""DICOM to NIfTI, plus automatic selection of the anatomical T1 series.

`dcm2niix` is preferred because it handles vendor quirks (mosaics, rescale
slopes, gantry tilt) that a pure-python reader gets wrong. `dicom2nifti` is the
fallback so the pipeline still runs if dcm2niix is missing.

A clinical export usually contains several series; we convert everything, then
score the results to find the 3D T1 that `charm` needs.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np

# Series descriptions that suggest a T1-weighted anatomical volume.
_T1_HINTS = ("mprage", "mp-rage", "t1", "spgr", "bravo", "tfl3d", "fspgr", "vibe")
# Descriptions that disqualify a series outright.
_REJECT_HINTS = (
    "t2", "flair", "dwi", "dti", "bold", "fmri", "perf", "asl", "swi",
    "localizer", "scout", "survey", "phoenix", "report", "screensave", "gre",
)


class ConversionError(RuntimeError):
    """Raised when no usable anatomical volume could be produced."""


def _find_dcm2niix() -> str | None:
    return shutil.which("dcm2niix")


def _run_dcm2niix(dicom_dir: Path, out_dir: Path, logger: logging.Logger) -> list[Path]:
    exe = _find_dcm2niix()
    if exe is None:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        "-z", "y",          # gzip output
        "-b", "y",          # write BIDS sidecar JSON, used for series scoring
        "-f", "%s_%d",      # <series number>_<series description>
        "-o", str(out_dir),
        str(dicom_dir),
    ]
    logger.info("Running dcm2niix")
    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        logger.warning(
            "dcm2niix exited with code %d; falling back. stderr: %s",
            proc.returncode,
            (proc.stderr or "").strip()[:500],
        )
        return []
    return sorted(out_dir.glob("*.nii.gz"))


def _run_dicom2nifti(dicom_dir: Path, out_dir: Path, logger: logging.Logger) -> list[Path]:
    try:
        import dicom2nifti
        import dicom2nifti.settings as d2n_settings
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ConversionError(
            "Neither dcm2niix nor dicom2nifti is available. Install dcm2niix "
            "(conda install -c conda-forge dcm2niix) or pip install dicom2nifti."
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    # Clinical exports frequently have small slice-spacing irregularities that
    # would otherwise abort the conversion outright.
    d2n_settings.disable_validate_slice_increment()
    logger.info("Running dicom2nifti (dcm2niix unavailable)")
    dicom2nifti.convert_directory(
        str(dicom_dir), str(out_dir), compression=True, reorient=True
    )
    return sorted(out_dir.glob("*.nii.gz"))


def _sidecar_for(nifti: Path) -> dict:
    sidecar = nifti.with_suffix("").with_suffix(".json")
    if sidecar.is_file():
        try:
            with open(sidecar, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _score_candidate(nifti: Path, logger: logging.Logger) -> float:
    """Rank a converted series by how much it looks like a 3D anatomical T1.

    Returns -inf for anything disqualified.
    """
    meta = _sidecar_for(nifti)
    # Search the sidecar fields AND the filename. dcm2niix encodes the series
    # description into the filename (-f %s_%d), so the filename carries the same
    # keyword even when no sidecar is written (the dicom2nifti fallback, or a
    # converter that omits it). Relying on the sidecar alone silently loses T1
    # detection whenever it is absent.
    description = " ".join(
        str(meta.get(k, "")) for k in ("SeriesDescription", "ProtocolName", "SequenceName")
    ).strip().lower()
    haystack = f"{description} {nifti.name.lower()}"

    if any(bad in haystack for bad in _REJECT_HINTS):
        return float("-inf")

    try:
        img = nib.load(str(nifti))
    except Exception as exc:  # noqa: BLE001 - nibabel raises many types
        logger.warning("Cannot read %s: %s", nifti.name, exc)
        return float("-inf")

    shape = img.shape
    if len(shape) != 3 or min(shape) < 40:
        # 4D series or a handful of slices: not an anatomical volume.
        return float("-inf")

    zooms = np.asarray(img.header.get_zooms()[:3], dtype=float)
    if np.any(zooms <= 0):
        return float("-inf")

    score = 0.0
    if any(hint in haystack for hint in _T1_HINTS):
        score += 100.0
    # Prefer near-isotropic, high-resolution volumes: charm segments those best.
    anisotropy = float(zooms.max() / zooms.min())
    score -= 20.0 * (anisotropy - 1.0)
    score -= 10.0 * max(0.0, float(zooms.max()) - 1.2)
    score += min(float(np.prod(shape)) / 1e6, 20.0)
    return score


def convert_subject(
    dicom_dir: Path,
    work_dir: Path,
    t1_out: Path,
    logger: logging.Logger,
) -> Path:
    """Convert `dicom_dir` and copy the best anatomical T1 to `t1_out`."""
    nifti_dir = work_dir / "nifti"
    if nifti_dir.exists():
        shutil.rmtree(nifti_dir)

    candidates = _run_dcm2niix(dicom_dir, nifti_dir, logger)
    if not candidates:
        candidates = _run_dicom2nifti(dicom_dir, nifti_dir, logger)
    if not candidates:
        raise ConversionError(f"Conversion produced no NIfTI files from {dicom_dir}")

    scored = sorted(
        ((_score_candidate(path, logger), path) for path in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    logger.info(
        "Converted %d series; best candidates: %s",
        len(candidates),
        ", ".join(f"{path.name}={score:.1f}" for score, path in scored[:5]),
    )

    best_score, best_path = scored[0]
    if best_score == float("-inf"):
        raise ConversionError(
            f"None of the {len(candidates)} converted series looks like a 3D "
            "anatomical T1. Point the pipeline at the MPRAGE/T1 series "
            "explicitly, or check the export."
        )
    if best_score < 50.0:
        # Nothing matched a T1 keyword; geometry alone chose the winner.
        logger.warning(
            "Best series %s scored only %.1f -- no T1 keyword matched. Verify "
            "the QC figure before trusting the head model.",
            best_path.name,
            best_score,
        )

    t1_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best_path, t1_out)
    logger.info("Selected %s as anatomical T1 -> %s", best_path.name, t1_out.name)
    return t1_out
