"""Batch runner: subject discovery and process-level parallelism.

Parallelism sits at the subject level because `charm` dominates the runtime and
is a separate process anyway. Workers are processes (loky), so on Windows the
caller *must* guard the entry point with `if __name__ == "__main__":` -- see
run_pipeline.py.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from joblib import Parallel, delayed

from .config import Config
from .pipeline import process_subject
from .preflight import run_preflight
from .qc import write_batch_summary

logger = logging.getLogger("mri2mne.batch")


def discover_subjects(config: Config) -> list[str]:
    """Resolve the subject list from config, honouring include/exclude."""
    if config.subjects.include:
        subjects = list(config.subjects.include)
    else:
        root = config.paths.dicom_root
        if not root.is_dir():
            raise FileNotFoundError(f"dicom_root does not exist: {root}")
        subjects = sorted(p.name for p in root.iterdir() if p.is_dir())

    excluded = set(config.subjects.exclude)
    subjects = [s for s in subjects if s not in excluded]
    if not subjects:
        raise ValueError(
            "No subjects to process. Check paths.dicom_root and the "
            "subjects.include / subjects.exclude settings."
        )
    return subjects


def run_batch(
    config: Config,
    subjects: list[str] | None = None,
    skip_preflight: bool = False,
) -> list[dict]:
    """Process every subject and write the batch summary."""
    subjects = subjects or discover_subjects(config)

    if not skip_preflight:
        report = run_preflight(config, subjects, logger)
        if not report.ok:
            raise RuntimeError(
                f"Preflight found {len(report.errors)} blocking problem(s); "
                "see the messages above. Fix them, or pass --skip-preflight to "
                "run anyway."
            )

    n_jobs = min(config.resolved_n_jobs(), len(subjects))

    logger.info(
        "Processing %d subject(s) with %d parallel worker(s)", len(subjects), n_jobs
    )
    if config.run.force:
        logger.info("Forcing re-run of stage(s): %s", ", ".join(config.run.force))

    start = time.monotonic()
    try:
        results = list(
            Parallel(n_jobs=n_jobs, backend="loky", verbose=5)(
                delayed(process_subject)(subject, config) for subject in subjects
            )
        )
    except Exception as exc:  # noqa: BLE001 - TerminatedWorkerError and kin
        # A worker *process* died rather than raising: almost always the OOM
        # killer taking out charm. joblib discards every result in that case,
        # including subjects that had already finished, so recover by replaying
        # sequentially. Stage caching makes the finished ones near-instant, and
        # one-at-a-time gives the subject that died the whole machine's memory.
        logger.error(
            "A worker process died (%s). This is almost always memory "
            "exhaustion -- consider lowering run.n_jobs.", type(exc).__name__,
        )
        logger.info(
            "Replaying %d subject(s) sequentially; completed stages are cached "
            "and will be skipped.", len(subjects),
        )
        results = [process_subject(subject, config) for subject in subjects]

    elapsed = time.monotonic() - start
    if not config.run.continue_on_error:
        failures = [r for r in results if r.get("status") == "failed"]
        if failures:
            names = ", ".join(str(r["subject"]) for r in failures)
            raise RuntimeError(f"Subject(s) failed and continue_on_error is off: {names}")

    summary_dir = config.paths.derivatives_root
    summary_html = write_batch_summary(results, summary_dir / "batch_summary.html")
    summary_json = summary_dir / "batch_summary.json"
    summary_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_flagged = sum(1 for r in results if r.get("status") == "flagged")
    n_failed = sum(1 for r in results if r.get("status") == "failed")
    logger.info(
        "Batch finished in %.1f min: %d ok, %d flagged, %d failed",
        elapsed / 60, n_ok, n_flagged, n_failed,
    )
    logger.info("Summary: %s", summary_html)

    for res in results:
        if res.get("status") == "failed":
            logger.error("  %s FAILED: %s", res["subject"], res.get("error"))
        elif res.get("status") == "flagged":
            logger.warning("  %s needs review: %s", res["subject"], res.get("flags"))

    return results
