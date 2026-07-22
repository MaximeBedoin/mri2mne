"""Per-subject orchestration.

Each stage declares a fingerprint over its inputs. If the fingerprint matches
what `status.json` recorded on the last successful run, the stage is skipped.
That is what makes re-running a forty-subject batch after a config tweak cheap:
only the affected stages recompute.
"""

from __future__ import annotations

import logging
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config
from .coregistration import (
    CoregistrationError,
    build_info,
    fit_coregistration,
    read_digitisation,
)
from .dicom_convert import convert_subject
from .freesurfer_bem import build_bem_anatomy
from .headmodel import find_charm, run_charm
from .logging_utils import get_logger
from .paths import StatusStore, SubjectPaths, fingerprint
from .simnibs_forward import make_fem_forward
from .simnibs_mesh import extract_coreg_inputs
from . import volumetric
from .qc import build_report


@contextmanager
def _timed(metrics: dict[str, float], stage: str, logger: logging.Logger):
    """Record a stage's wall-clock time.

    Written into status.json so a pilot run on one subject tells you what the
    full batch will cost, rather than having to guess.
    """
    start = time.monotonic()
    yield
    elapsed = time.monotonic() - start
    metrics[f"t_{stage}_s"] = round(elapsed, 1)
    logger.info("Stage '%s' took %.1f s", stage, elapsed)


def _stage_needed(
    status: StatusStore,
    stage: str,
    fp: str,
    force: list[str],
    outputs: list[Path],
    logger: logging.Logger,
) -> bool:
    """Decide whether `stage` must run.

    A cached stage whose outputs have since been deleted is re-run: the cache
    records that we did the work, not that the files still exist.
    """
    if stage in force:
        logger.info("Stage '%s': forced re-run", stage)
        status.invalidate(stage)
        return True
    if not status.is_done(stage, fp):
        return True
    missing = [p for p in outputs if not p.exists()]
    if missing:
        logger.info(
            "Stage '%s': cached but output missing (%s); re-running",
            stage, ", ".join(p.name for p in missing),
        )
        return True
    logger.info("Stage '%s': up to date, skipping", stage)
    return False


def process_subject(subject: str, config: Config) -> dict[str, Any]:
    """Run the full pipeline for one subject. Never raises; returns a result."""
    paths = SubjectPaths(
        subject=subject,
        derivatives_root=config.paths.derivatives_root,
        subjects_dir=config.paths.subjects_dir,
    )
    paths.ensure_dirs()
    logger = get_logger(subject, paths.log_file)
    status = StatusStore(paths.status_file)
    force = config.run.force

    result: dict[str, Any] = {"subject": subject, "status": "failed", "flags": ""}
    metrics: dict[str, float] = dict(status.metrics)

    try:
        dicom_dir = config.paths.dicom_root / subject
        if not dicom_dir.is_dir():
            raise FileNotFoundError(f"No DICOM folder for {subject} at {dicom_dir}")

        # --- 1. DICOM -> NIfTI ------------------------------------------------
        fp = fingerprint(dicom_dir, config.anonymize.enabled, config.anonymize.deface)
        if _stage_needed(status, "convert", fp, force, [paths.t1_nifti], logger):
            with _timed(metrics, "convert", logger):
                _run_convert(paths, config, dicom_dir, logger)
            status.mark_done("convert", fp, elapsed_s=metrics.get("t_convert_s"))

        bem_route = config.head_model == "bem"

        # --- 2. Head model: SimNIBS charm (FEM) or FreeSurfer BEM (WSL) -------
        if bem_route:
            _bem = paths.fs_subject_dir / "bem"
            _xfm = paths.fs_subject_dir / "mri" / "transforms" / "talairach.xfm"
            outputs = [_bem / "inner_skull.surf", _bem / "outer_skin.surf", _xfm]
            fp = fingerprint(
                paths.t1_nifti, config.bem.freesurfer_home or "",
                config.bem.wsl_distro or "",
            )
            if _stage_needed(status, "headmodel", fp, force, outputs, logger):
                with _timed(metrics, "headmodel", logger):
                    build_bem_anatomy(
                        paths, paths.t1_nifti, distro=config.bem.wsl_distro,
                        freesurfer_home=config.bem.freesurfer_home,
                        overwrite="headmodel" in force, logger=logger,
                    )
                status.mark_done("headmodel", fp, elapsed_s=metrics.get("t_headmodel_s"))
        else:
            t2 = config.t2_for(subject)
            fp = fingerprint(paths.t1_nifti, t2, *config.simnibs.extra_args)
            if _stage_needed(
                status, "headmodel", fp, force,
                [paths.final_tissues, paths.tissue_lut], logger,
            ):
                with _timed(metrics, "headmodel", logger):
                    run_charm(
                        subject=subject,
                        t1=paths.t1_nifti,
                        work_dir=paths.root,
                        m2m_dir=paths.m2m_dir,
                        charm_exe=find_charm(config.simnibs.bin_dir),
                        logger=logger,
                        t2=t2,
                        extra_args=config.simnibs.extra_args,
                        timeout_s=config.simnibs.timeout_s,
                        force="headmodel" in force,
                        n_threads=config.threads_per_worker(),
                    )
                status.mark_done("headmodel", fp, elapsed_s=metrics.get("t_headmodel_s"))

        # --- 3. Coregistration (MNE, shared; inputs differ per route) ---------
        dig_path = config.digitisation_for(subject)
        anat_input = (
            paths.fs_subject_dir / "bem" / "inner_skull.surf" if bem_route
            else paths.final_tissues
        )
        fp = fingerprint(
            dig_path, anat_input,
            config.coregistration.icp_iterations,
            config.coregistration.omit_distance_mm,
        )
        montage = read_digitisation(dig_path, logger)
        info = build_info(montage, logger)

        if _stage_needed(status, "coreg", fp, force, [paths.trans], logger):
            with _timed(metrics, "coreg", logger):
                if bem_route:
                    volumetric.prepare_coreg_inputs(paths, logger)
                else:
                    extract_coreg_inputs(paths, config.simnibs.bin_dir, logger)
                _, coreg_metrics = fit_coregistration(
                    paths, info,
                    icp_iterations=config.coregistration.icp_iterations,
                    omit_distance_mm=config.coregistration.omit_distance_mm,
                    logger=logger,
                )
            metrics.update(coreg_metrics)
            status.mark_done("coreg", fp, elapsed_s=metrics.get("t_coreg_s"))

        # --- 4. Forward: SimNIBS FEM (surface) or MNE BEM (volume) ------------
        if bem_route:
            fp = fingerprint(paths.trans, dig_path, config.bem.pos_mm, config.bem.ico)
            if _stage_needed(status, "forward", fp, force, [paths.volume_forward], logger):
                import mne

                with _timed(metrics, "forward", logger):
                    volumetric.make_bem(
                        paths, logger, conductivity=config.bem.conductivity,
                        ico=config.bem.ico, strict=config.bem.strict,
                    )
                    volumetric.setup_volume_source(paths, logger, pos_mm=config.bem.pos_mm)
                    trans = mne.read_trans(str(paths.trans))
                    fwd = volumetric.make_volume_forward(paths, info, trans, logger)
                    metrics["fwd_n_sources"] = float(fwd["nsource"])
                    metrics["fwd_n_channels"] = float(fwd["nchan"])
                status.mark_done("forward", fp, elapsed_s=metrics.get("t_forward_s"))
        else:
            fp = fingerprint(paths.trans, dig_path, config.fem.subsampling)
            if _stage_needed(status, "forward", fp, force, [paths.forward], logger):
                import mne

                trans = mne.read_trans(str(paths.trans))
                with _timed(metrics, "forward", logger):
                    _, fwd_metrics = make_fem_forward(
                        paths, info, trans, config.simnibs.bin_dir, logger,
                        subsampling=config.fem.subsampling, cpus=config.fem.cpus,
                        morph_to_fsaverage=config.fem.morph_to_fsaverage,
                        timeout_s=config.simnibs.timeout_s,
                    )
                metrics.update(fwd_metrics)
                status.mark_done("forward", fp, elapsed_s=metrics.get("t_forward_s"))

        # --- 6. QC -------------------------------------------------------------
        flags = _evaluate_flags(metrics, config)
        distances = _dig_distances_mm(paths, info, logger)
        build_report(
            paths, info, metrics, flags,
            max_residual_mm=config.coregistration.max_residual_mm,
            logger=logger, coreg_distances_mm=distances,
        )

        status.metrics.update(metrics)
        status.save()

        result.update(
            status="flagged" if flags else "ok",
            flags="; ".join(flags),
            coreg_residual_median_mm=metrics.get("coreg_residual_median_mm"),
            fwd_n_sources=metrics.get("fwd_n_sources"),
            fwd_n_channels=metrics.get("fwd_n_channels"),
            report=str(paths.report) if paths.report.is_file() else None,
        )
        logger.info("Subject completed with status '%s'", result["status"])

    except Exception as exc:  # noqa: BLE001 - batch must survive one bad subject
        message = f"{type(exc).__name__}: {exc}"
        logger.error("Subject failed: %s", message)
        logger.debug("%s", traceback.format_exc())
        result["error"] = message
        result["status"] = "failed"

    return result


def _run_convert(
    paths: SubjectPaths, config: Config, dicom_dir: Path, logger: logging.Logger
) -> None:
    """Anonymise if requested, convert, optionally write a defaced copy."""
    import shutil

    from .anonymize import anonymize_dicom_dir, deface_nifti

    anon_dir = paths.root / "dicom_anon"
    work_dir = paths.root / "work"

    source_dir = dicom_dir
    if config.anonymize.enabled:
        source_dir = anonymize_dicom_dir(dicom_dir, anon_dir, paths.subject, logger)

    convert_subject(source_dir, work_dir, paths.t1_nifti, logger)

    if config.anonymize.deface:
        # Deliberately a separate file. Defacing before segmentation would strip
        # scalp and frontal bone that charm depends on; charm always gets the
        # intact T1, and this copy exists purely for sharing data outward.
        deface_nifti(paths.t1_nifti, paths.t1_defaced, logger)

    if config.run.cleanup_intermediates:
        # The anonymised DICOM copy and the other converted series have served
        # their purpose; only the T1 goes further. Roughly 2-3 GB per subject,
        # and the originals under dicom_root are untouched, so this is
        # reproducible from source at any time.
        for path in (anon_dir, work_dir):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        logger.info("Removed conversion intermediates")


def _dig_distances_mm(paths: SubjectPaths, info, logger: logging.Logger):
    """Recompute point-to-scalp distances for the QC histogram."""
    try:
        import mne

        distances = mne.dig_mri_distances(
            info, str(paths.trans), paths.subject,
            subjects_dir=str(paths.subjects_dir), verbose="ERROR",
        )
        return np.asarray(distances, dtype=float) * 1000.0
    except Exception as exc:  # noqa: BLE001 - QC extra, not load-bearing
        logger.warning("Could not recompute dig-MRI distances: %s", exc)
        return None


def _evaluate_flags(metrics: dict[str, float], config: Config) -> list[str]:
    """Conditions that make a subject suspect without making it a failure."""
    flags: list[str] = []

    residual = metrics.get("coreg_residual_median_mm")
    if residual is not None and np.isfinite(residual):
        if residual > config.coregistration.max_residual_mm:
            flags.append(
                f"coregistration residual {residual:.2f} mm exceeds "
                f"{config.coregistration.max_residual_mm:.1f} mm"
            )

    # A low dig->scalp residual does NOT prove the pose is right: on a smooth
    # scalp, ICP can settle a centimetre off while every point still sits close
    # to the surface. Validation on MNE's `sample` showed a 1.7 mm residual
    # hiding an ~8 mm pose error. The fiducial-only residual reflects fiducial
    # quality, which is what actually pins the pose, so flag when it is poor
    # even though ICP later drove the head-shape residual down.
    initial = metrics.get("coreg_residual_initial_median_mm")
    if initial is not None and np.isfinite(initial) and initial > 12.0:
        flags.append(
            f"fiducial-only alignment was {initial:.1f} mm before ICP; the pose "
            "may be a centimetre off despite a low final residual -- verify the "
            "alignment figure"
        )

    n_sources = metrics.get("fwd_n_sources")
    if n_sources is not None and n_sources < 1000:
        flags.append(f"only {int(n_sources)} sources in the forward solution")

    return flags
