"""Tests for the volumetric BEM route -- path layout and wrapper validation.

The heavy steps (FreeSurfer, BEM) are integration-validated on real data; here
we cover the pure logic: the distinct volumetric file names, the BEM surface
quality metric on synthetic surfaces, and the wrapper's anatomy-input guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne.paths import SubjectPaths  # noqa: E402


def _paths(tmp_path: Path) -> SubjectPaths:
    return SubjectPaths(
        subject="sub01",
        derivatives_root=tmp_path / "deriv",
        subjects_dir=tmp_path / "deriv" / "subjects",
    )


def test_volume_paths_are_distinct_from_surface(tmp_path):
    p = _paths(tmp_path)
    # Volumetric outputs must not collide with the surface FEM route's files.
    assert p.volume_source_space.name == "sub01-vol-src.fif"
    assert p.volume_forward.name == "sub01-vol-fwd.fif"
    assert p.volume_inverse.name == "sub01-vol-inv.fif"
    assert p.bem_solution.name == "sub01-bem-sol.fif"
    assert p.volume_source_estimate.name == "sub01-vol"
    # distinct from the surface source space
    assert p.volume_source_space != p.source_space
    assert p.surf_dir == p.subjects_dir / "sub01" / "surf"


def test_reconstruct_volumetric_requires_exactly_one_anatomy(tmp_path):
    from mri2mne.wrapper import reconstruct_sources_volumetric

    common = dict(
        subject="s", output_dir=tmp_path,
        eeg_file=tmp_path / "e.edf", digitization=tmp_path / "d.fif",
    )
    with pytest.raises(ValueError):  # neither
        reconstruct_sources_volumetric(**common)
    with pytest.raises(ValueError):  # both
        reconstruct_sources_volumetric(
            dicom_dir=tmp_path / "dcm", t1_path=tmp_path / "t1.nii", **common)


def test_check_bem_surfaces_aggregates_violations(tmp_path, monkeypatch):
    """The metric must count inner->outer and outer->skin violations correctly.

    Mocks MNE's surface primitives so we test the aggregation, not geometry
    (the geometry is validated end-to-end on real watershed surfaces).
    """
    import mne.surface as ms
    from mri2mne import volumetric as V

    p = _paths(tmp_path)
    rr = np.zeros((100, 3))

    monkeypatch.setattr(ms, "read_surface", lambda f: (rr.copy(), np.zeros((1, 3), int)))
    monkeypatch.setattr(ms, "complete_surface_info",
                        lambda s, **k: {"rr": s["rr"]})

    calls = {"n": 0}

    def fake_outside(points, surf, **kw):
        # first call = inner-vs-outer (7 outside), second = outer-vs-skin (0)
        calls["n"] += 1
        mask = np.zeros(len(points), bool)
        if calls["n"] == 1:
            mask[:7] = True
        return mask

    monkeypatch.setattr(ms, "_points_outside_surface", fake_outside)

    q = V.check_bem_surfaces(p)
    assert q["bem_inner_outside_outer"] == 7.0
    assert q["bem_outer_outside_skin"] == 0.0
    assert q["bem_n_vertices"] == 100.0
