"""Tests for configuration loading and validation.

A malformed config must fail immediately, not two hours into a charm run.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne.config import ConfigError, load_config  # noqa: E402

MINIMAL = """\
paths:
  dicom_root: "D:/data/dicom"
  derivatives_root: "D:/data/deriv"
  subjects_dir: "D:/data/deriv/subjects"
  digitisation: "D:/data/dig/{subject}.elc"
"""


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_minimal_config_loads(tmp_path: Path):
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.paths.dicom_root == Path("D:/data/dicom")
    assert config.fem.subsampling == 10000
    assert config.fem.morph_to_fsaverage == 5
    assert config.run.continue_on_error is True


def test_fem_settings_are_read(tmp_path: Path):
    text = MINIMAL + "fem:\n  subsampling: 20000\n  morph_to_fsaverage: null\n"
    config = load_config(write_config(tmp_path, text))
    assert config.fem.subsampling == 20000
    assert config.fem.morph_to_fsaverage is None


def test_digitisation_needs_subject_placeholder(tmp_path: Path):
    bad = MINIMAL.replace('"D:/data/dig/{subject}.elc"', '"D:/data/dig/all.elc"')
    with pytest.raises(ConfigError, match=r"\{subject\}"):
        load_config(write_config(tmp_path, bad))


def test_missing_required_path_is_fatal(tmp_path: Path):
    bad = MINIMAL.replace('  subjects_dir: "D:/data/deriv/subjects"\n', "")
    with pytest.raises(ConfigError, match="subjects_dir"):
        load_config(write_config(tmp_path, bad))


def test_unknown_force_stage_is_rejected(tmp_path: Path):
    bad = MINIMAL + "run:\n  force: [headmodel, teleport]\n"
    with pytest.raises(ConfigError, match="teleport"):
        load_config(write_config(tmp_path, bad))


def test_subject_substitution(tmp_path: Path):
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.digitisation_for("sub-007") == Path("D:/data/dig/sub-007.elc")


def test_head_model_defaults_to_fem(tmp_path: Path):
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.head_model == "fem"
    assert config.bem.pos_mm == 5.0  # defaults present even when unused


def test_head_model_bem_reads_bem_section(tmp_path: Path):
    text = MINIMAL + (
        'head_model: bem\n'
        'bem:\n'
        '  pos_mm: 6.0\n'
        '  ico: 3\n'
        '  strict: false\n'
        '  conductivity: [0.33, 0.0042, 0.33]\n'
        '  wsl_distro: Ubuntu\n'
    )
    config = load_config(write_config(tmp_path, text))
    assert config.head_model == "bem"
    assert config.bem.pos_mm == 6.0
    assert config.bem.ico == 3
    assert config.bem.strict is False
    assert config.bem.conductivity == (0.33, 0.0042, 0.33)
    assert config.bem.wsl_distro == "Ubuntu"


def test_invalid_head_model_is_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="head_model"):
        load_config(write_config(tmp_path, MINIMAL + "head_model: teleport\n"))


def test_bem_conductivity_must_be_three_values(tmp_path: Path):
    bad = MINIMAL + "head_model: bem\nbem:\n  conductivity: [0.3, 0.006]\n"
    with pytest.raises(ConfigError, match="conductivity"):
        load_config(write_config(tmp_path, bad))


def test_n_jobs_defaults_to_quarter_of_cores(tmp_path: Path):
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.resolved_n_jobs() >= 1

    config.run.n_jobs = 3
    assert config.resolved_n_jobs() == 3


def test_cleanup_intermediates_defaults_on(tmp_path: Path):
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.run.cleanup_intermediates is True


def test_cleanup_intermediates_can_be_disabled(tmp_path: Path):
    text = MINIMAL + "run:\n  cleanup_intermediates: false\n"
    config = load_config(write_config(tmp_path, text))
    assert config.run.cleanup_intermediates is False


def test_missing_config_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


class TestForcesformDetection:
    """charm rejects a T1 with qform_code 0; the pipeline should detect that."""

    def _write_nifti(self, path, qform_code, sform_code):
        import logging

        import nibabel as nib
        import numpy as np

        img = nib.Nifti1Image(np.zeros((8, 8, 8), dtype=np.float32), np.eye(4))
        img.set_qform(np.eye(4), code=qform_code)
        img.set_sform(np.eye(4), code=sform_code)
        nib.save(img, str(path))
        return logging.getLogger("test-forcesform")

    def test_valid_qform_needs_no_flag(self, tmp_path: Path):
        from mri2mne.headmodel import _needs_forcesform

        log = self._write_nifti(tmp_path / "t1.nii.gz", qform_code=1, sform_code=1)
        assert _needs_forcesform(tmp_path / "t1.nii.gz", log) is False

    def test_zero_qform_with_sform_triggers_flag(self, tmp_path: Path):
        from mri2mne.headmodel import _needs_forcesform

        log = self._write_nifti(tmp_path / "t1.nii.gz", qform_code=0, sform_code=1)
        assert _needs_forcesform(tmp_path / "t1.nii.gz", log) is True

    def test_no_geometry_does_not_crash(self, tmp_path: Path):
        from mri2mne.headmodel import _needs_forcesform

        log = self._write_nifti(tmp_path / "t1.nii.gz", qform_code=0, sform_code=0)
        # Neither set: cannot help via --forcesform, but must not raise.
        assert _needs_forcesform(tmp_path / "t1.nii.gz", log) is False
