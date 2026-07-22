"""Per-subject directory layout and the stage cache.

Every stage records completion in `status.json` together with a fingerprint of
its inputs. Re-running the batch therefore skips finished work, but a changed
input (a re-exported DICOM series, a new digitisation file) invalidates the
affected stage automatically instead of silently reusing stale output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SubjectPaths:
    """Resolved locations for one subject."""

    subject: str
    derivatives_root: Path
    subjects_dir: Path

    @property
    def root(self) -> Path:
        return self.derivatives_root / self.subject

    @property
    def anat_dir(self) -> Path:
        return self.root / "anat"

    @property
    def t1_nifti(self) -> Path:
        return self.anat_dir / f"{self.subject}_T1w.nii.gz"

    @property
    def t1_defaced(self) -> Path:
        """Defaced copy for sharing. Never fed to charm: the geometric cut
        removes scalp and frontal bone that the segmentation needs."""
        return self.anat_dir / f"{self.subject}_T1w_defaced.nii.gz"

    @property
    def m2m_dir(self) -> Path:
        """SimNIBS head-model folder. charm names it `m2m_<subid>`."""
        return self.root / f"m2m_{self.subject}"

    @property
    def final_tissues(self) -> Path:
        return self.m2m_dir / "final_tissues.nii.gz"

    @property
    def tissue_lut(self) -> Path:
        return self.m2m_dir / "final_tissues_LUT.txt"

    # --- FreeSurfer-style layout that MNE expects ---------------------------
    # MNE addresses coregistration inputs through a FreeSurfer-style
    # subjects_dir/<subject>/bem layout; we synthesise just that folder (no
    # FreeSurfer is run) to hold the scalp head surface and the fiducials.
    @property
    def fs_subject_dir(self) -> Path:
        return self.subjects_dir / self.subject

    @property
    def fs_bem_dir(self) -> Path:
        return self.fs_subject_dir / "bem"

    @property
    def surf_dir(self) -> Path:
        """FreeSurfer-style surf/ folder. Populated on demand by `viz` with the
        SimNIBS cortical mesh written as lh/rh.white, so MNE's surface plotting
        treats the subject as an ordinary FreeSurfer subject."""
        return self.fs_subject_dir / "surf"

    @property
    def head_surface(self) -> Path:
        """Scalp surface (from the SimNIBS mesh) that ICP fits against."""
        return self.fs_bem_dir / f"{self.subject}-head.fif"

    @property
    def fiducials(self) -> Path:
        return self.fs_bem_dir / f"{self.subject}-fiducials.fif"

    # --- MNE outputs ---------------------------------------------------------
    @property
    def mne_dir(self) -> Path:
        return self.root / "mne"

    @property
    def source_space(self) -> Path:
        """Cortical (surface) source space from the SimNIBS FEM forward."""
        return self.mne_dir / f"{self.subject}-src.fif"

    # --- volumetric BEM route (FreeSurfer/WSL), kept distinct from the -------
    # surface FEM outputs so a subject can carry both without clobbering.
    @property
    def bem_solution(self) -> Path:
        return self.mne_dir / f"{self.subject}-bem-sol.fif"

    @property
    def volume_source_space(self) -> Path:
        return self.mne_dir / f"{self.subject}-vol-src.fif"

    @property
    def volume_forward(self) -> Path:
        return self.mne_dir / f"{self.subject}-vol-fwd.fif"

    @property
    def volume_inverse(self) -> Path:
        return self.mne_dir / f"{self.subject}-vol-inv.fif"

    @property
    def volume_source_estimate(self) -> Path:
        """Stem; MNE appends '-vl.stc' for a volume source estimate."""
        return self.mne_dir / f"{self.subject}-vol"

    @property
    def trans(self) -> Path:
        return self.mne_dir / f"{self.subject}-trans.fif"

    @property
    def forward(self) -> Path:
        return self.mne_dir / f"{self.subject}-fwd.fif"

    @property
    def noise_cov(self) -> Path:
        return self.mne_dir / f"{self.subject}-noise-cov.fif"

    @property
    def inverse(self) -> Path:
        return self.mne_dir / f"{self.subject}-inv.fif"

    @property
    def source_estimate(self) -> Path:
        """MNE appends '-lh.stc' / '-rh.stc' for a surface source estimate, so
        this is a stem, not a complete filename."""
        return self.mne_dir / f"{self.subject}"

    @property
    def evoked(self) -> Path:
        return self.mne_dir / f"{self.subject}-ave.fif"

    # --- bookkeeping ---------------------------------------------------------
    @property
    def qc_dir(self) -> Path:
        return self.root / "qc"

    @property
    def report(self) -> Path:
        return self.qc_dir / f"{self.subject}_report.html"

    @property
    def log_file(self) -> Path:
        return self.root / "logs" / f"{self.subject}.log"

    @property
    def status_file(self) -> Path:
        return self.root / "status.json"

    def ensure_dirs(self) -> None:
        for d in (
            self.anat_dir,
            self.mne_dir,
            self.qc_dir,
            self.fs_bem_dir,
            self.log_file.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)


def fingerprint(*items: Path | str | float | int | None) -> str:
    """Cheap, stable fingerprint of a stage's inputs.

    Files contribute their size and mtime rather than their contents: hashing a
    multi-gigabyte DICOM series on every run would cost more than the stage we
    are trying to skip.
    """
    h = hashlib.sha256()
    for item in items:
        if item is None:
            h.update(b"\x00none")
        elif isinstance(item, Path):
            if item.is_file():
                st = item.stat()
                h.update(f"{item.name}:{st.st_size}:{int(st.st_mtime)}".encode())
            elif item.is_dir():
                # Directory of DICOMs: aggregate over the immediate file list.
                entries = sorted(p for p in item.rglob("*") if p.is_file())
                h.update(f"dir:{len(entries)}".encode())
                for p in entries[:2000]:
                    st = p.stat()
                    h.update(f"{p.name}:{st.st_size}".encode())
            else:
                h.update(b"\x00missing")
        else:
            h.update(str(item).encode())
    return h.hexdigest()[:16]


class StatusStore:
    """Reads/writes `status.json`, the per-subject stage cache."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {"stages": {}}
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                # A truncated status file means we lost the cache, not the data.
                # Re-running the stages is always safe, so start clean.
                self._data = {"stages": {}}
        self._data.setdefault("stages", {})

    def is_done(self, stage: str, input_fingerprint: str) -> bool:
        entry = self._data["stages"].get(stage)
        if not entry or entry.get("state") != "ok":
            return False
        return entry.get("fingerprint") == input_fingerprint

    def mark_done(self, stage: str, input_fingerprint: str, **extra: Any) -> None:
        self._data["stages"][stage] = {
            "state": "ok",
            "fingerprint": input_fingerprint,
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **extra,
        }
        self.save()

    def mark_failed(self, stage: str, message: str) -> None:
        self._data["stages"][stage] = {
            "state": "failed",
            "error": message,
            "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.save()

    def invalidate(self, stage: str) -> None:
        self._data["stages"].pop(stage, None)

    def get(self, stage: str) -> dict[str, Any] | None:
        return self._data["stages"].get(stage)

    @property
    def metrics(self) -> dict[str, Any]:
        return self._data.setdefault("metrics", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        tmp.replace(self.path)
