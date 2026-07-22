"""Checks run before the batch starts.

A forty-subject batch is an overnight commitment. Nearly every way it goes
wrong -- a missing digitisation file, charm not on PATH, a full disk -- is
knowable in seconds beforehand. This module front-loads those checks so the
batch either starts clean or refuses to start.

Errors abort the run. Warnings are reported and the run proceeds.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .headmodel import HeadModelError, find_charm
from .simnibs_forward import ForwardError, simnibs_python

# Rough derivatives footprint per subject: charm's m2m folder + FEM leadfield +
# the anonymised DICOM copy. Deliberately generous.
_DISK_PER_SUBJECT_GB = 5.0


@dataclass
class PreflightReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def log(self, logger: logging.Logger) -> None:
        for message in self.info:
            logger.info("preflight: %s", message)
        for message in self.warnings:
            logger.warning("preflight: %s", message)
        for message in self.errors:
            logger.error("preflight: %s", message)


def _check_tools(config: Config, report: PreflightReport) -> None:
    if config.head_model == "bem":
        _check_freesurfer_wsl(config, report)
    else:
        _check_simnibs(config, report)

    if shutil.which("dcm2niix"):
        report.info.append("dcm2niix available")
    else:
        # Catch Exception, not ImportError: a package compiled against another
        # numpy ABI raises ValueError at import, and a preflight check that
        # crashes is worse than useless.
        try:
            import dicom2nifti  # noqa: F401

            report.warnings.append(
                "dcm2niix not on PATH; falling back to dicom2nifti, which is "
                "less robust with vendor-specific DICOM quirks."
            )
        except Exception as exc:  # noqa: BLE001
            report.errors.append(
                "Neither dcm2niix nor dicom2nifti is usable, so DICOM "
                f"conversion cannot run ({type(exc).__name__}: {exc}). "
                "conda install -c conda-forge dcm2niix"
            )


def _check_simnibs(config: Config, report: PreflightReport) -> None:
    """FEM route: charm executable + SimNIBS' own Python."""
    try:
        charm = find_charm(config.simnibs.bin_dir)
        report.info.append(f"charm found at {charm}")
    except HeadModelError as exc:
        report.errors.append(str(exc))
    try:
        py = simnibs_python(config.simnibs.bin_dir)
        report.info.append(f"SimNIBS Python at {py}")
    except ForwardError as exc:
        report.errors.append(str(exc))


def _check_freesurfer_wsl(config: Config, report: PreflightReport) -> None:
    """BEM route: WSL reachable + a licensed FreeSurfer inside it."""
    from . import wsl

    if not wsl.is_available(config.bem.wsl_distro):
        report.errors.append(
            "WSL is not available, but head_model is 'bem'. Install WSL2 "
            "(`wsl --install`) or switch head_model to 'fem'."
        )
        return
    fs = wsl.check_freesurfer(config.bem.wsl_distro, config.bem.freesurfer_home)
    if fs.present and fs.has_license:
        report.info.append(f"FreeSurfer (WSL): {fs.describe()}")
    else:
        report.errors.append(
            f"FreeSurfer not usable in WSL for the BEM route: {fs.describe()}. "
            "See the README 'Route volumique' setup."
        )


def _check_disk(config: Config, n_subjects: int, report: PreflightReport) -> None:
    root = config.paths.derivatives_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".mri2mne_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        report.errors.append(f"derivatives_root {root} is not writable: {exc}")
        return

    free_gb = shutil.disk_usage(root).free / 1e9
    needed_gb = n_subjects * _DISK_PER_SUBJECT_GB
    if free_gb < needed_gb:
        report.errors.append(
            f"Only {free_gb:.0f} GB free on {root}, but {n_subjects} subjects "
            f"need roughly {needed_gb:.0f} GB. Free space or move "
            "derivatives_root to a larger volume."
        )
    else:
        report.info.append(
            f"{free_gb:.0f} GB free, ~{needed_gb:.0f} GB estimated for "
            f"{n_subjects} subject(s)"
        )


def _check_subject_inputs(
    config: Config, subjects: list[str], report: PreflightReport
) -> None:
    missing_dicom: list[str] = []
    empty_dicom: list[str] = []
    missing_dig: list[str] = []
    missing_t2: list[str] = []

    for subject in subjects:
        dicom_dir = config.paths.dicom_root / subject
        if not dicom_dir.is_dir():
            missing_dicom.append(subject)
        elif not any(p.is_file() for p in dicom_dir.rglob("*")):
            empty_dicom.append(subject)

        if not config.digitisation_for(subject).is_file():
            missing_dig.append(subject)

        t2 = config.t2_for(subject)
        if t2 is not None and not t2.is_file():
            missing_t2.append(subject)

    def summarise(names: list[str]) -> str:
        shown = ", ".join(names[:8])
        return shown + (f" (+{len(names) - 8} more)" if len(names) > 8 else "")

    if missing_dicom:
        report.errors.append(
            f"No DICOM folder for {len(missing_dicom)} subject(s): "
            f"{summarise(missing_dicom)}"
        )
    if empty_dicom:
        report.errors.append(
            f"DICOM folder is empty for {len(empty_dicom)} subject(s): "
            f"{summarise(empty_dicom)}"
        )
    if missing_dig:
        # Hard error: without electrode positions there is no coregistration
        # and therefore no forward solution. Better to know now.
        report.errors.append(
            f"No digitisation file for {len(missing_dig)} subject(s): "
            f"{summarise(missing_dig)}. Expected at "
            f"{config.paths.digitisation}"
        )
    if missing_t2:
        report.warnings.append(
            f"Configured T2 missing for {len(missing_t2)} subject(s): "
            f"{summarise(missing_t2)}. Those will be processed T1-only."
        )


def run_preflight(
    config: Config, subjects: list[str], logger: logging.Logger
) -> PreflightReport:
    """Validate tools, resources and per-subject inputs."""
    report = PreflightReport()

    n_jobs = min(config.resolved_n_jobs(), max(1, len(subjects)))
    report.info.append(
        f"{len(subjects)} subject(s), {n_jobs} worker(s), "
        f"{config.threads_per_worker()} thread(s) per worker"
    )

    _check_tools(config, report)
    _check_disk(config, len(subjects), report)
    _check_subject_inputs(config, subjects, report)

    report.log(logger)
    return report
