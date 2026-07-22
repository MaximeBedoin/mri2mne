"""Tests for the SimNIBS->FreeSurfer surface bridge used by visualisation.

Only the pure-Python bridge is exercised (no OpenGL): given a two-hemisphere
surface source space, the right FreeSurfer surface files must appear with the
mesh intact, the call must be idempotent, and a volumetric space must be
rejected rather than silently mishandled.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne.paths import SubjectPaths  # noqa: E402
from mri2mne import viz  # noqa: E402


def _fake_surf_hemi(n=6):
    """A tiny valid surface: an octahedron-ish patch (rr in metres, tris)."""
    rr = np.array(
        [[0, 0, 1], [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0], [0, 0, -1]],
        dtype=float,
    ) * 0.05  # ~5 cm, metres
    tris = np.array(
        [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
         [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]],
        dtype=np.int32,
    )
    return {"type": "surf", "rr": rr, "tris": tris, "np": len(rr),
            "ntri": len(tris), "nuse": len(rr)}


def _paths(tmp_path: Path) -> SubjectPaths:
    return SubjectPaths(
        subject="sub01",
        derivatives_root=tmp_path / "deriv",
        subjects_dir=tmp_path / "deriv" / "subjects",
    )


def test_writes_freesurfer_surfaces(tmp_path, monkeypatch):
    import mne

    paths = _paths(tmp_path)
    paths.source_space.parent.mkdir(parents=True, exist_ok=True)
    paths.source_space.write_bytes(b"stub")  # existence check only

    src = [_fake_surf_hemi(), _fake_surf_hemi()]
    monkeypatch.setattr(mne, "read_source_spaces", lambda *a, **k: src)

    subjects_dir = viz.write_freesurfer_surfaces(paths, overwrite=True)
    assert subjects_dir == paths.subjects_dir

    for hemi in ("lh", "rh"):
        for name in ("white", "pial", "inflated"):
            f = paths.surf_dir / f"{hemi}.{name}"
            assert f.is_file()
            rr, tris = mne.read_surface(str(f))
            assert rr.shape == (6, 3)
            assert tris.shape == (8, 3)
            # rr was written in millimetres (0.05 m -> 50 mm)
            assert np.isclose(np.abs(rr).max(), 50.0)


def test_idempotent_skip(tmp_path, monkeypatch):
    import mne

    paths = _paths(tmp_path)
    paths.source_space.parent.mkdir(parents=True, exist_ok=True)
    paths.source_space.write_bytes(b"stub")

    calls = {"n": 0}

    def counting_reader(*a, **k):
        calls["n"] += 1
        return [_fake_surf_hemi(), _fake_surf_hemi()]

    monkeypatch.setattr(mne, "read_source_spaces", counting_reader)

    viz.write_freesurfer_surfaces(paths, overwrite=True)
    assert calls["n"] == 1
    viz.write_freesurfer_surfaces(paths)          # files present -> skip
    assert calls["n"] == 1                        # reader not called again


def test_rejects_volumetric(tmp_path, monkeypatch):
    import mne

    paths = _paths(tmp_path)
    paths.source_space.parent.mkdir(parents=True, exist_ok=True)
    paths.source_space.write_bytes(b"stub")

    vol = [{"type": "vol", "rr": np.zeros((3, 3)), "tris": None}]
    monkeypatch.setattr(mne, "read_source_spaces", lambda *a, **k: vol)

    with pytest.raises(viz.VizError):
        viz.write_freesurfer_surfaces(paths, overwrite=True)


def test_missing_source_space_raises(tmp_path):
    paths = _paths(tmp_path)  # nothing on disk
    with pytest.raises(viz.VizError):
        viz.write_freesurfer_surfaces(paths, overwrite=True)
