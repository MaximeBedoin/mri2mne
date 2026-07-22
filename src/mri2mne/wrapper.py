"""One-call, single-subject entry point: raw files in, source estimate out.

    from mri2mne.wrapper import reconstruct_sources

    result = reconstruct_sources(
        subject="patient01",
        output_dir="D:/derivatives",
        dicom_dir="D:/dicom/patient01",
        eeg_file="D:/eeg/patient01.edf",
        digitization="D:/dig/patient01.elc",
        simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",
    )
    print(result.source_estimate_file, result.peak)

The anatomy stages (DICOM -> charm -> coreg -> FEM forward)
are delegated to the batch pipeline, so they inherit its caching, QC and
resume behaviour. This wrapper adds the EEG half: read, preprocess, covariance,
inverse operator, and the source estimate itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .logging_utils import get_logger
from .paths import SubjectPaths

@dataclass
class SourceResult:
    """Everything produced for one subject, with the source estimate on top."""

    subject: str
    status: str
    forward_file: Path | None = None
    inverse_file: Path | None = None
    noise_cov_file: Path | None = None
    source_estimate_file: Path | None = None
    report_file: Path | None = None
    peak: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stc: Any = None  # the in-memory VolSourceEstimate, for immediate use


def reconstruct_sources(
    subject: str,
    output_dir: str | Path,
    *,
    # --- anatomy input (need a T1 from somewhere) --------------------------
    dicom_dir: str | Path | None = None,
    t1_path: str | Path | None = None,
    t2_path: str | Path | None = None,
    # --- EEG + electrode positions -----------------------------------------
    eeg_file: str | Path,
    digitization: str | Path,
    # --- SimNIBS ------------------------------------------------------------
    simnibs_bin_dir: str | Path | None = None,
    # --- FEM forward / cortical source space --------------------------------
    fem_subsampling: int | None = 10000,   # cortical sources per hemisphere
    fem_cpus: int = 1,                       # parallel FEM electrode solves
    morph_to_fsaverage: int | None = 5,      # fsaverage morph for group analysis
    # --- coregistration -----------------------------------------------------
    icp_iterations: int = 20,
    omit_distance_mm: float = 15.0,
    # --- EEG processing -----------------------------------------------------
    l_freq: float | None = 1.0,
    h_freq: float | None = 40.0,
    eeg_reference: str | None = "average",
    events: Sequence | str | Path | None = None,
    event_id: dict | int | None = None,
    tmin: float = -0.2,
    tmax: float = 0.5,
    baseline: tuple[float | None, float | None] | None = (None, 0.0),
    reject: dict | None = None,
    noise_cov_tmin: float | None = None,
    noise_cov_tmax: float | None = 0.0,
    # --- inverse ------------------------------------------------------------
    inverse_method: str = "dSPM",
    snr: float = 3.0,
    # --- control ------------------------------------------------------------
    anonymize: bool = True,
    deface: bool = False,
    force: Sequence[str] = (),
    n_jobs: int = 1,
) -> SourceResult:
    """Go from raw files (DICOM MRI + EEG) to an EEG source estimate.

    Parameters
    ----------
    subject : str
        Identifier used for all output filenames.
    output_dir : path
        Root for every derivative this subject produces.
    dicom_dir, t1_path : path, optional
        The anatomy source. Give a DICOM folder (converted and segmented) or,
        to skip conversion, a ready NIfTI T1. Exactly one is required.
    t2_path : path, optional
        A T2 image markedly improves skull segmentation if your protocol has one.
    eeg_file : path
        The recording to localise (.edf, .bdf, .vhdr, .set, .fif, ...).
    digitization : path
        Digitised electrode positions. Labels must match the EEG channels.
    simnibs_bin_dir : path
        SimNIBS Scripts folder. Locates charm and the SimNIBS Python that runs
        the FEM leadfield. Required for the FEM forward.
    fem_subsampling : int | None
        Cortical source points per hemisphere for the leadfield (default 10000).
    fem_cpus : int
        Parallel electrode solves in the FEM leadfield.
    morph_to_fsaverage : int | None
        fsaverage subdivision to also produce a group-analysis morph (or None).
    events, event_id, tmin, tmax, baseline, reject
        Standard MNE epoching. With events, epochs are averaged into an evoked
        response before localisation; without, the whole recording is localised
        as one segment.
    noise_cov_tmin, noise_cov_tmax
        Window for the noise covariance (defaults to the pre-stimulus baseline).
    inverse_method : {'dSPM','MNE','sLORETA','eLORETA'}
    snr : float
        Assumed SNR; sets the regularisation (lambda2 = 1/snr**2).

    Returns
    -------
    SourceResult
        Output paths, the peak location, and the in-memory source estimate.
    """
    output_dir = Path(output_dir)
    eeg_file = Path(eeg_file)
    digitization = Path(digitization)
    dicom_dir = Path(dicom_dir) if dicom_dir else None
    t1_path = Path(t1_path) if t1_path else None
    t2_path = Path(t2_path) if t2_path else None
    simnibs_bin_dir = Path(simnibs_bin_dir) if simnibs_bin_dir else None

    if (dicom_dir is None) == (t1_path is None):
        raise ValueError("Provide exactly one of dicom_dir or t1_path.")

    force = list(force)
    paths = SubjectPaths(subject=subject, derivatives_root=output_dir,
                         subjects_dir=output_dir / "subjects")
    paths.ensure_dirs()
    logger = get_logger(subject, paths.log_file)
    result = SourceResult(subject=subject, status="failed")

    try:
        _run_anatomy(
            paths=paths, dicom_dir=dicom_dir, t1_path=t1_path, t2_path=t2_path,
            digitization=digitization, simnibs_bin_dir=simnibs_bin_dir,
            fem_subsampling=fem_subsampling, fem_cpus=fem_cpus,
            morph_to_fsaverage=morph_to_fsaverage,
            icp_iterations=icp_iterations, omit_distance_mm=omit_distance_mm,
            anonymize=anonymize, deface=deface,
            force=force, logger=logger, result=result,
        )
        _run_inverse(
            paths, eeg_file, digitization, l_freq, h_freq, eeg_reference,
            events, event_id, tmin, tmax, baseline, reject,
            noise_cov_tmin, noise_cov_tmax, inverse_method, snr, logger, result,
        )
        result.status = "ok"
        logger.info("Source reconstruction complete for %s", subject)
    except Exception as exc:  # noqa: BLE001 - report, never explode on the caller
        import traceback

        result.error = f"{type(exc).__name__}: {exc}"
        logger.error("Source reconstruction failed: %s", result.error)
        logger.debug("%s", traceback.format_exc())

    return result


def _run_anatomy(
    *, paths, dicom_dir, t1_path, t2_path, digitization, simnibs_bin_dir,
    fem_subsampling, fem_cpus, morph_to_fsaverage, icp_iterations,
    omit_distance_mm, anonymize, deface, force, logger, result,
) -> None:
    """Run DICOM/T1 -> forward as a linear sequence of stage functions.

    Deliberately not routed through the batch `process_subject`: that couples
    the subject id to the DICOM folder name and drives everything from path
    templates, which fits a directory of subjects but fights a single explicit
    one. Skipping is by output existence here, honouring `force`; the batch
    runner remains the fingerprint-cached path.
    """
    import shutil

    from .coregistration import build_info, fit_coregistration, read_digitisation
    from .dicom_convert import convert_subject
    from .headmodel import find_charm, run_charm
    from .simnibs_forward import make_fem_forward
    from .simnibs_mesh import extract_coreg_inputs

    force = set(force)

    def needs(stage: str, *outputs: Path) -> bool:
        if stage in force:
            return True
        return not all(Path(o).exists() for o in outputs)

    # --- 1. T1 (convert DICOM, or copy a supplied NIfTI) -------------------
    if needs("convert", paths.t1_nifti):
        if t1_path is not None:
            paths.t1_nifti.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(t1_path, paths.t1_nifti)
            logger.info("Using supplied T1 %s", t1_path)
        else:
            from .anonymize import anonymize_dicom_dir, deface_nifti

            source_dir = dicom_dir
            if anonymize:
                source_dir = anonymize_dicom_dir(
                    dicom_dir, paths.root / "dicom_anon", paths.subject, logger)
            convert_subject(source_dir, paths.root / "work", paths.t1_nifti, logger)
            if deface:
                deface_nifti(paths.t1_nifti, paths.t1_defaced, logger)

    # --- 2. SimNIBS charm (full run: mesh + surfaces are needed) -----------
    if needs("headmodel", paths.final_tissues, paths.tissue_lut):
        run_charm(
            subject=paths.subject, t1=paths.t1_nifti, work_dir=paths.root,
            m2m_dir=paths.m2m_dir, charm_exe=find_charm(simnibs_bin_dir),
            logger=logger, t2=t2_path, force="headmodel" in force,
        )

    # --- 3. Coregistration inputs from the SimNIBS mesh, then MNE coreg -----
    montage = read_digitisation(digitization, logger)
    info = build_info(montage, logger)
    if needs("coreg", paths.trans):
        extract_coreg_inputs(paths, simnibs_bin_dir, logger)
        _, coreg_metrics = fit_coregistration(
            paths, info, icp_iterations=icp_iterations,
            omit_distance_mm=omit_distance_mm, logger=logger)
        result.metrics.update(coreg_metrics)

    # --- 4. FEM forward via SimNIBS ----------------------------------------
    if needs("forward", paths.forward):
        import mne

        trans = mne.read_trans(str(paths.trans))
        _, fwd_metrics = make_fem_forward(
            paths, info, trans, simnibs_bin_dir, logger,
            subsampling=fem_subsampling, cpus=fem_cpus,
            morph_to_fsaverage=morph_to_fsaverage,
        )
        result.metrics.update(fwd_metrics)

    if not paths.forward.is_file():
        raise RuntimeError("Head-model stages finished but produced no forward.")
    result.forward_file = paths.forward
    logger.info("FEM forward ready: %s", paths.forward)


def _run_inverse(
    paths, eeg_file, digitization, l_freq, h_freq, eeg_reference,
    events, event_id, tmin, tmax, baseline, reject,
    noise_cov_tmin, noise_cov_tmax, inverse_method, snr, logger, result,
) -> None:
    """Read the EEG and turn the forward model into a source estimate."""
    import mne

    from .coregistration import read_digitisation
    from .eeg import (
        attach_montage,
        build_evoked,
        compute_noise_cov,
        preprocess,
        read_eeg,
    )
    from .inverse import apply_inverse_evoked, make_inverse, peak_location

    raw = read_eeg(eeg_file, logger)
    montage = read_digitisation(digitization, logger)
    raw = attach_montage(raw, montage, logger)
    raw = preprocess(raw, l_freq, h_freq, eeg_reference, logger)

    events_array = _resolve_events(events, raw, logger)
    evoked, epochs = build_evoked(
        raw, events_array, event_id, tmin, tmax, baseline, reject, logger,
    )
    evoked.save(str(paths.evoked), overwrite=True, verbose="ERROR")

    noise_cov = compute_noise_cov(
        epochs if events_array is not None else raw,
        noise_cov_tmin, noise_cov_tmax, logger,
    )
    mne.write_cov(str(paths.noise_cov), noise_cov, overwrite=True, verbose="ERROR")
    result.noise_cov_file = paths.noise_cov

    inv = make_inverse(paths, evoked.info, noise_cov, logger)
    result.inverse_file = paths.inverse

    stc = apply_inverse_evoked(paths, evoked, inv, inverse_method, snr, logger)
    result.stc = stc
    # Surface source estimate: MNE writes -lh.stc / -rh.stc.
    result.source_estimate_file = Path(str(paths.source_estimate) + "-lh.stc")

    src = mne.read_source_spaces(str(paths.source_space), verbose="ERROR")
    result.peak = peak_location(stc, src, logger)


def _resolve_events(events, raw, logger):
    """Accept an events array, a path to an -eve.fif, or 'find' to auto-detect."""
    import mne

    if events is None:
        return None
    if isinstance(events, (str, Path)):
        if str(events) == "find":
            found = mne.find_events(raw, verbose="ERROR")
            logger.info("Auto-detected %d events from the trigger channel", len(found))
            return found
        return mne.read_events(str(events))
    return events


def reconstruct_sources_volumetric(
    subject: str,
    output_dir: str | Path,
    *,
    # --- anatomy input -----------------------------------------------------
    dicom_dir: str | Path | None = None,
    t1_path: str | Path | None = None,
    # --- EEG + electrode positions -----------------------------------------
    eeg_file: str | Path,
    digitization: str | Path,
    # --- WSL / FreeSurfer ---------------------------------------------------
    wsl_distro: str | None = None,
    freesurfer_home: str | None = None,
    # --- volumetric BEM head model / source space --------------------------
    pos_mm: float = 5.0,
    conductivity: tuple[float, float, float] = (0.3, 0.006, 0.3),
    bem_ico: int | None = 4,
    bem_strict: bool = True,
    # --- coregistration -----------------------------------------------------
    icp_iterations: int = 20,
    omit_distance_mm: float = 15.0,
    # --- EEG processing -----------------------------------------------------
    l_freq: float | None = 1.0,
    h_freq: float | None = 40.0,
    eeg_reference: str | None = "average",
    events: Sequence | str | Path | None = None,
    event_id: dict | int | None = None,
    tmin: float = -0.2,
    tmax: float = 0.5,
    baseline: tuple[float | None, float | None] | None = (None, 0.0),
    reject: dict | None = None,
    noise_cov_tmin: float | None = None,
    noise_cov_tmax: float | None = 0.0,
    # --- inverse ------------------------------------------------------------
    inverse_method: str = "dSPM",
    snr: float = 3.0,
    loose: float = 1.0,
    depth: float = 0.8,
    # --- control ------------------------------------------------------------
    anonymize: bool = True,
    force: Sequence[str] = (),
) -> SourceResult:
    """Go from raw files to a VOLUMETRIC EEG source estimate (Route C).

    The FreeSurfer/WSL variant: DICOM/T1 -> recon-all -autorecon1 + watershed
    (in WSL) -> 3-layer BEM -> volume source space -> coregistration -> forward
    -> inverse, yielding a volume source estimate (``-vl.stc``). Independent of
    the SimNIBS surface route: it lives entirely in the FreeSurfer MRI frame.

    Mirrors `reconstruct_sources` but for the BEM/volumetric head model; see it
    for the shared EEG/epoching arguments. Requires WSL2 with a licensed
    FreeSurfer (see `wsl.check_freesurfer`).
    """
    output_dir = Path(output_dir)
    eeg_file = Path(eeg_file)
    digitization = Path(digitization)
    dicom_dir = Path(dicom_dir) if dicom_dir else None
    t1_path = Path(t1_path) if t1_path else None

    if (dicom_dir is None) == (t1_path is None):
        raise ValueError("Provide exactly one of dicom_dir or t1_path.")

    force = set(force)
    paths = SubjectPaths(subject=subject, derivatives_root=output_dir,
                         subjects_dir=output_dir / "subjects")
    paths.ensure_dirs()
    logger = get_logger(subject, paths.log_file)
    result = SourceResult(subject=subject, status="failed")

    try:
        info = _run_anatomy_volumetric(
            paths=paths, dicom_dir=dicom_dir, t1_path=t1_path,
            digitization=digitization, wsl_distro=wsl_distro,
            freesurfer_home=freesurfer_home, pos_mm=pos_mm,
            conductivity=conductivity, bem_ico=bem_ico, bem_strict=bem_strict,
            icp_iterations=icp_iterations, omit_distance_mm=omit_distance_mm,
            anonymize=anonymize, force=force, logger=logger, result=result,
        )
        _run_inverse_volumetric(
            paths, info, eeg_file, digitization, l_freq, h_freq, eeg_reference,
            events, event_id, tmin, tmax, baseline, reject,
            noise_cov_tmin, noise_cov_tmax, inverse_method, snr, loose, depth,
            logger, result,
        )
        result.status = "ok"
        logger.info("Volumetric source reconstruction complete for %s", subject)
    except Exception as exc:  # noqa: BLE001 - report, never explode on the caller
        import traceback

        result.error = f"{type(exc).__name__}: {exc}"
        logger.error("Volumetric reconstruction failed: %s", result.error)
        logger.debug("%s", traceback.format_exc())

    return result


def _run_anatomy_volumetric(
    *, paths, dicom_dir, t1_path, digitization, wsl_distro, freesurfer_home,
    pos_mm, conductivity, bem_ico, bem_strict, icp_iterations, omit_distance_mm,
    anonymize, force, logger, result,
):
    """DICOM/T1 -> FreeSurfer BEM anatomy -> coreg -> BEM volume forward."""
    import shutil

    import mne

    from .coregistration import build_info, fit_coregistration, read_digitisation
    from .dicom_convert import convert_subject
    from .freesurfer_bem import build_bem_anatomy
    from . import volumetric as V

    def needs(stage: str, *outputs: Path) -> bool:
        return stage in force or not all(Path(o).exists() for o in outputs)

    # 1. T1
    if needs("convert", paths.t1_nifti):
        if t1_path is not None:
            paths.t1_nifti.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(t1_path, paths.t1_nifti)
            logger.info("Using supplied T1 %s", t1_path)
        else:
            from .anonymize import anonymize_dicom_dir

            source_dir = dicom_dir
            if anonymize:
                source_dir = anonymize_dicom_dir(
                    dicom_dir, paths.root / "dicom_anon", paths.subject, logger)
            convert_subject(source_dir, paths.root / "work", paths.t1_nifti, logger)

    # 2. FreeSurfer BEM anatomy (autorecon1 + watershed, via WSL)
    build_bem_anatomy(
        paths, paths.t1_nifti, distro=wsl_distro,
        freesurfer_home=freesurfer_home, overwrite="headmodel" in force,
        logger=logger,
    )

    # 3. Coregistration (shared code, FreeSurfer MRI frame)
    montage = read_digitisation(digitization, logger)
    info = build_info(montage, logger)
    if needs("coreg", paths.trans):
        V.prepare_coreg_inputs(paths, logger)
        _, coreg_metrics = fit_coregistration(
            paths, info, icp_iterations=icp_iterations,
            omit_distance_mm=omit_distance_mm, logger=logger)
        result.metrics.update(coreg_metrics)

    # 4. BEM + volume source space + forward
    if needs("forward", paths.volume_forward):
        V.make_bem(paths, logger, conductivity=conductivity, ico=bem_ico,
                   strict=bem_strict)
        V.setup_volume_source(paths, logger, pos_mm=pos_mm)
        trans = mne.read_trans(str(paths.trans))
        fwd = V.make_volume_forward(paths, info, trans, logger)
        result.metrics["fwd_n_sources"] = float(fwd["nsource"])
        result.metrics["fwd_n_channels"] = float(fwd["nchan"])

    result.forward_file = paths.volume_forward
    return info


def _run_inverse_volumetric(
    paths, info, eeg_file, digitization, l_freq, h_freq, eeg_reference,
    events, event_id, tmin, tmax, baseline, reject,
    noise_cov_tmin, noise_cov_tmax, inverse_method, snr, loose, depth,
    logger, result,
):
    """Read the EEG and turn the volume forward into a volume source estimate."""
    import mne

    from .coregistration import read_digitisation
    from .eeg import (
        attach_montage,
        build_evoked,
        compute_noise_cov,
        preprocess,
        read_eeg,
    )
    from . import volumetric as V

    raw = read_eeg(eeg_file, logger)
    montage = read_digitisation(digitization, logger)
    raw = attach_montage(raw, montage, logger)
    raw = preprocess(raw, l_freq, h_freq, eeg_reference, logger)

    events_array = _resolve_events(events, raw, logger)
    evoked, epochs = build_evoked(
        raw, events_array, event_id, tmin, tmax, baseline, reject, logger,
    )
    evoked.save(str(paths.evoked), overwrite=True, verbose="ERROR")

    noise_cov = compute_noise_cov(
        epochs if events_array is not None else raw,
        noise_cov_tmin, noise_cov_tmax, logger,
    )
    mne.write_cov(str(paths.noise_cov), noise_cov, overwrite=True, verbose="ERROR")
    result.noise_cov_file = paths.noise_cov

    inv = V.make_volume_inverse(paths, evoked.info, noise_cov, logger,
                                loose=loose, depth=depth)
    result.inverse_file = paths.volume_inverse

    stc = V.apply_volume_inverse(paths, evoked, inv, inverse_method, snr, logger)
    result.stc = stc
    result.source_estimate_file = Path(str(paths.volume_source_estimate) + "-vl.stc")

    src = mne.read_source_spaces(str(paths.volume_source_space), verbose="ERROR")
    result.peak = V.peak_location_volume(stc, src, logger)
