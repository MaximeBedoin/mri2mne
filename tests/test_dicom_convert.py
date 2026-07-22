"""Tests for the DICOM->NIfTI series scorer.

The full stage (real dcm2niix on a synthesized DICOM series) is exercised by a
scratch script during development; here we pin the series-scoring logic, whose
sidecar-vs-filename fallback caused a real T1-detection miss.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne.dicom_convert import _score_candidate  # noqa: E402


@pytest.fixture
def logger():
    log = logging.getLogger("test-dicom")
    log.addHandler(logging.NullHandler())
    return log


def _write_nifti(path: Path, shape=(64, 64, 64), zooms=(1.0, 1.0, 1.0)):
    affine = np.diag([*zooms, 1.0])
    nib.save(nib.Nifti1Image(np.zeros(shape, dtype=np.int16), affine), str(path))
    return path


def test_t1_keyword_in_filename_without_sidecar(tmp_path: Path, logger):
    """No sidecar: the T1 keyword must still be found in the filename.

    This is the regression: a whitespace-only description used to bypass the
    filename fallback, dropping the +100 T1 bonus.
    """
    nifti = _write_nifti(tmp_path / "2_mprage_t1.nii.gz")
    score = _score_candidate(nifti, logger)
    assert score > 100, f"expected T1 bonus, got {score}"


def test_isotropic_scores_higher_than_anisotropic(tmp_path: Path, logger):
    iso = _score_candidate(_write_nifti(tmp_path / "a_mprage.nii.gz",
                                        zooms=(1.0, 1.0, 1.0)), logger)
    aniso = _score_candidate(_write_nifti(tmp_path / "b_mprage.nii.gz",
                                          zooms=(1.0, 1.0, 4.0)), logger)
    assert iso > aniso


def test_localizer_in_filename_is_rejected(tmp_path: Path, logger):
    score = _score_candidate(_write_nifti(tmp_path / "1_localizer.nii.gz"), logger)
    assert score == float("-inf")


def test_too_few_slices_rejected(tmp_path: Path, logger):
    thin = _write_nifti(tmp_path / "3_mprage.nii.gz", shape=(64, 64, 8))
    assert _score_candidate(thin, logger) == float("-inf")


def test_flair_rejected_even_if_3d(tmp_path: Path, logger):
    score = _score_candidate(_write_nifti(tmp_path / "5_t2_flair.nii.gz"), logger)
    assert score == float("-inf")
