"""Tests for the EEG / inverse / wrapper layer.

Heavy paths (reading a real EDF, solving a real inverse) are covered by
examples/validate_inverse_on_sample.py on real data. These unit tests pin the
logic that does not need a full dataset: format dispatch, channel matching,
method validation, peak indexing, and the wrapper's argument handling.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne.eeg import EEGError, read_eeg  # noqa: E402
from mri2mne.inverse import InverseError, peak_location  # noqa: E402
from mri2mne.wrapper import reconstruct_sources  # noqa: E402


@pytest.fixture
def logger():
    log = logging.getLogger("test-eeg")
    log.addHandler(logging.NullHandler())
    return log


class TestReadEeg:
    def test_missing_file_raises(self, tmp_path: Path, logger):
        with pytest.raises(EEGError, match="not found"):
            read_eeg(tmp_path / "nope.edf", logger)

    def test_unsupported_format_raises(self, tmp_path: Path, logger):
        bogus = tmp_path / "recording.xyz"
        bogus.write_text("not eeg", encoding="utf-8")
        with pytest.raises(EEGError, match="Unsupported EEG format"):
            read_eeg(bogus, logger)


class TestAttachMontage:
    """attach_montage aligns EEG labels to digitised labels."""

    def _raw(self, names):
        import mne

        info = mne.create_info(list(names), sfreq=100.0, ch_types="eeg")
        return mne.io.RawArray(np.zeros((len(names), 10)), info, verbose="ERROR")

    def _montage(self, names):
        import mne

        pos = {n: np.array([0.01 * i, 0.0, 0.08]) for i, n in enumerate(names)}
        return mne.channels.make_dig_montage(
            ch_pos=pos, lpa=[-0.08, 0, 0], nasion=[0, 0.09, 0], rpa=[0.08, 0, 0],
            coord_frame="head",
        )

    def test_exact_match(self, logger):
        from mri2mne.eeg import attach_montage

        raw = self._raw(["C3", "C4", "Cz"])
        raw = attach_montage(raw, self._montage(["C3", "C4", "Cz"]), logger)
        assert set(raw.ch_names) == {"C3", "C4", "Cz"}

    def test_case_insensitive_rescue(self, logger):
        """EEG 'FP1' should still match digitisation 'Fp1'."""
        from mri2mne.eeg import attach_montage

        raw = self._raw(["FP1", "FP2"])
        raw = attach_montage(raw, self._montage(["Fp1", "Fp2"]), logger)
        assert len(raw.ch_names) == 2

    def test_unpositioned_channel_dropped(self, logger):
        from mri2mne.eeg import attach_montage

        raw = self._raw(["C3", "C4", "EXTRA"])
        raw = attach_montage(raw, self._montage(["C3", "C4"]), logger)
        assert "EXTRA" not in raw.ch_names
        assert len(raw.ch_names) == 2

    def test_no_overlap_raises(self, logger):
        from mri2mne.eeg import attach_montage

        raw = self._raw(["A1", "A2"])
        with pytest.raises(EEGError, match="No EEG channel label matches"):
            attach_montage(raw, self._montage(["Z9", "Z8"]), logger)


class TestPeakLocation:
    def test_peak_maps_to_mri_mm(self, logger):
        """The reported peak must be the RAS position of the strongest source."""

        class FakeStc:
            def __init__(self, data):
                self.data = data

            def get_peak(self, vert_as_index, time_as_index):
                # Strongest source is index 2.
                return 2, 0.11

        # Four sources; positions in metres (MRI surface RAS).
        rr = np.array([[0, 0, 0], [0.01, 0, 0], [-0.04, -0.02, 0.03], [0, 0.05, 0]])
        src = [{"rr": rr, "vertno": np.arange(4)}]
        data = np.zeros((4, 5))
        data[2, 3] = 9.0
        peak = peak_location(FakeStc(data), src, logger)

        assert peak["peak_mri_x_mm"] == pytest.approx(-40.0)
        assert peak["peak_mri_y_mm"] == pytest.approx(-20.0)
        assert peak["peak_mri_z_mm"] == pytest.approx(30.0)
        assert peak["peak_amplitude"] == pytest.approx(9.0)


class TestWrapperArgs:
    def test_requires_exactly_one_anatomy_source(self, tmp_path: Path):
        with pytest.raises(ValueError, match="exactly one of dicom_dir or t1_path"):
            reconstruct_sources(
                "sub", tmp_path, eeg_file=tmp_path / "e.edf",
                digitization=tmp_path / "d.elc",
            )

    def test_both_anatomy_sources_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="exactly one of dicom_dir or t1_path"):
            reconstruct_sources(
                "sub", tmp_path, dicom_dir=tmp_path / "dcm", t1_path=tmp_path / "t1.nii",
                eeg_file=tmp_path / "e.edf", digitization=tmp_path / "d.elc",
            )

    def test_runtime_failure_is_captured_not_raised(self, tmp_path: Path):
        """A missing input during a stage returns a failed result, not a crash:
        the wrapper is meant to be safe to call in a loop."""
        result = reconstruct_sources(
            "sub", tmp_path, t1_path=tmp_path / "does_not_exist.nii.gz",
            eeg_file=tmp_path / "e.edf", digitization=tmp_path / "d.elc",
        )
        assert result.status == "failed"
        assert result.error is not None
        assert result.source_estimate_file is None
