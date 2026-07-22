"""Tests for the WSL bridge -- the parts that need no running WSL.

Path translation is pure Python; the FreeSurfer probe is tested by feeding
`wsl.run` synthetic output so the parsing is checked without a live distro.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mri2mne import wsl  # noqa: E402


@pytest.mark.parametrize(
    "win,expected",
    [
        (r"C:\Users\me\t1.nii.gz", "/mnt/c/Users/me/t1.nii.gz"),
        (r"D:\data\sub01", "/mnt/d/data/sub01"),
        (r"E:\a b\c", "/mnt/e/a b/c"),
        ("/already/posix", "/already/posix"),
    ],
)
def test_to_wsl_path(win, expected):
    assert wsl.to_wsl_path(win) == expected


def test_to_wsl_path_rejects_relative():
    with pytest.raises(wsl.WslError):
        wsl.to_wsl_path(r"relative\path")


def test_from_wsl_path_roundtrip():
    assert str(wsl.from_wsl_path("/mnt/d/data/sub01")) == r"D:\data\sub01"
    with pytest.raises(wsl.WslError):
        wsl.from_wsl_path("/home/user/thing")  # not under /mnt/<drive>


def _fake_run(stdout):
    return lambda *a, **k: wsl.WslResult(0, stdout, "")


def test_check_freesurfer_present(monkeypatch):
    out = (
        "HOME=/usr/local/freesurfer/7.4.1\n"
        "VER=freesurfer-linux-ubuntu22_amd64-7.4.1\n"
        "/usr/local/freesurfer/7.4.1/bin/mri_convert\n"
        "/usr/local/freesurfer/7.4.1/bin/mri_watershed\n"
        "LICENSE_OK\n"
    )
    monkeypatch.setattr(wsl, "run", _fake_run(out))
    info = wsl.check_freesurfer()
    assert info.present and info.has_license
    assert info.home == "/usr/local/freesurfer/7.4.1"
    assert info.missing == []


def test_check_freesurfer_absent(monkeypatch):
    monkeypatch.setattr(wsl, "run", _fake_run("HOME=\nVER=\n"))
    info = wsl.check_freesurfer()
    assert not info.present
    assert not info.has_license
    assert set(info.missing) == {"mri_convert", "mri_watershed"}


def test_check_freesurfer_no_license(monkeypatch):
    out = (
        "HOME=/opt/freesurfer\n"
        "VER=\n"
        "/opt/freesurfer/bin/mri_convert\n"
        "/opt/freesurfer/bin/mri_watershed\n"
    )
    monkeypatch.setattr(wsl, "run", _fake_run(out))
    info = wsl.check_freesurfer()
    assert info.present            # binaries there
    assert not info.has_license    # but no license.txt
    assert "license.txt not found" in info.describe()
