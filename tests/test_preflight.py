"""Tests for the preflight checks.

The point of preflight is to turn an overnight batch that dies at hour three
into a five-second refusal, so the checks that matter most are the ones about
per-subject inputs.
"""

from __future__ import annotations

import logging
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne.config import load_config  # noqa: E402
from mri2mne.preflight import PreflightReport, _check_subject_inputs  # noqa: E402


@pytest.fixture
def logger():
    log = logging.getLogger("test-preflight")
    log.addHandler(logging.NullHandler())
    return log


@pytest.fixture
def config(tmp_path: Path):
    """A config whose paths all live under tmp_path."""
    (tmp_path / "dicom").mkdir()
    (tmp_path / "dig").mkdir()
    text = textwrap.dedent(f"""\
        paths:
          dicom_root: "{(tmp_path / 'dicom').as_posix()}"
          derivatives_root: "{(tmp_path / 'deriv').as_posix()}"
          subjects_dir: "{(tmp_path / 'deriv' / 'subjects').as_posix()}"
          digitisation: "{(tmp_path / 'dig').as_posix()}/{{subject}}.elc"
    """)
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def make_subject(config, name: str, *, dicom=True, empty=False, dig=True) -> None:
    if dicom:
        subject_dir = config.paths.dicom_root / name
        subject_dir.mkdir(parents=True, exist_ok=True)
        if not empty:
            (subject_dir / "IM001.dcm").write_bytes(b"not really dicom")
    if dig:
        path = config.digitisation_for(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dummy", encoding="utf-8")


class TestSubjectInputs:
    def test_complete_subject_passes(self, config):
        make_subject(config, "sub-001")
        report = PreflightReport()
        _check_subject_inputs(config, ["sub-001"], report)
        assert report.errors == []

    def test_missing_dicom_folder_is_error(self, config):
        make_subject(config, "sub-001", dicom=False)
        report = PreflightReport()
        _check_subject_inputs(config, ["sub-001"], report)
        assert any("No DICOM folder" in e for e in report.errors)

    def test_empty_dicom_folder_is_error(self, config):
        make_subject(config, "sub-001", empty=True)
        report = PreflightReport()
        _check_subject_inputs(config, ["sub-001"], report)
        assert any("empty" in e for e in report.errors)

    def test_missing_digitisation_is_error(self, config):
        """Without electrodes there is no forward solution, so this blocks."""
        make_subject(config, "sub-001", dig=False)
        report = PreflightReport()
        _check_subject_inputs(config, ["sub-001"], report)
        assert any("digitisation" in e for e in report.errors)

    def test_reports_every_bad_subject_not_just_the_first(self, config):
        for i in range(1, 4):
            make_subject(config, f"sub-{i:03d}", dig=False)
        report = PreflightReport()
        _check_subject_inputs(config, [f"sub-{i:03d}" for i in range(1, 4)], report)
        message = " ".join(report.errors)
        assert "3 subject(s)" in message
        for i in range(1, 4):
            assert f"sub-{i:03d}" in message

    def test_many_bad_subjects_are_summarised(self, config):
        names = [f"sub-{i:03d}" for i in range(1, 15)]
        for name in names:
            make_subject(config, name, dig=False)
        report = PreflightReport()
        _check_subject_inputs(config, names, report)
        assert any("+6 more" in e for e in report.errors)

    def test_missing_t2_is_only_a_warning(self, config, tmp_path: Path):
        make_subject(config, "sub-001")
        config.simnibs.t2_template = str(tmp_path / "t2" / "{subject}_T2.nii.gz")
        report = PreflightReport()
        _check_subject_inputs(config, ["sub-001"], report)
        assert report.errors == []
        assert any("T2 missing" in w for w in report.warnings)


class TestReport:
    def test_ok_reflects_errors_only(self):
        report = PreflightReport()
        assert report.ok

        report.warnings.append("something suboptimal")
        assert report.ok, "warnings must not block the batch"

        report.errors.append("something fatal")
        assert not report.ok


class TestThreadAllocation:
    def test_threads_divide_among_workers(self, config, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 16)

        config.run.n_jobs = 4
        assert config.threads_per_worker() == 4

        config.run.n_jobs = 3
        assert config.threads_per_worker() == 5

    def test_never_returns_zero(self, config, monkeypatch):
        """More workers than cores must still give each worker one thread."""
        monkeypatch.setattr("os.cpu_count", lambda: 4)
        config.run.n_jobs = 16
        assert config.threads_per_worker() == 1


class TestFemConfig:
    def test_fem_defaults(self, config):
        assert config.fem.subsampling == 10000
        assert config.fem.cpus == 1

    def test_fem_is_read(self, tmp_path: Path):
        text = textwrap.dedent("""\
            paths:
              dicom_root: "D:/d"
              derivatives_root: "D:/x"
              subjects_dir: "D:/x/s"
              digitisation: "D:/g/{subject}.elc"
            fem:
              subsampling: 15000
        """)
        path = tmp_path / "c.yaml"
        path.write_text(text, encoding="utf-8")
        assert load_config(path).fem.subsampling == 15000
