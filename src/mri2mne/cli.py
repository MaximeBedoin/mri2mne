"""Batch command-line entry point (installed as the ``mri2mne`` console script).

    mri2mne --config config.yaml
    mri2mne --config config.yaml --subjects sub-001 sub-002
    mri2mne --config config.yaml --force coreg forward

When run from a source checkout without installing, ``run_pipeline.py`` at the
repo root is a thin wrapper that puts ``src/`` on the path and calls ``main()``
here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import STAGES
from .batch import discover_subjects, run_batch
from .config import ConfigError, load_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mri2mne",
        description="DICOM MRI + EEG -> MNE source-analysis pipeline (batch).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.yaml"),
        help="Path to the YAML configuration file.",
    )
    parser.add_argument(
        "--subjects", nargs="+", default=None,
        help="Process only these subjects, overriding subjects.include.",
    )
    parser.add_argument(
        "--force", nargs="+", default=None, choices=list(STAGES),
        help="Re-run these stages even if cached.",
    )
    parser.add_argument(
        "--n-jobs", type=int, default=None,
        help="Parallel subjects. Overrides run.n_jobs.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List the subjects that would be processed, then exit.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Run preflight checks only (tools, BLAS, inputs, disk), then exit.",
    )
    parser.add_argument(
        "--skip-preflight", action="store_true",
        help="Start the batch even if preflight reports blocking problems.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.force is not None:
        config.run.force = list(args.force)
    if args.n_jobs is not None:
        config.run.n_jobs = args.n_jobs

    try:
        subjects = args.subjects or discover_subjects(config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot determine subjects: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Would process {len(subjects)} subject(s) "
              f"with {min(config.resolved_n_jobs(), len(subjects))} worker(s):")
        for subject in subjects:
            print(f"  {subject}")
        return 0

    if args.check:
        from .preflight import run_preflight

        report = run_preflight(config, subjects, logging.getLogger("mri2mne.batch"))
        if report.ok:
            print(f"\nPreflight passed ({len(report.warnings)} warning(s)).")
            return 0
        print(f"\nPreflight found {len(report.errors)} blocking problem(s).",
              file=sys.stderr)
        return 2

    try:
        results = run_batch(config, subjects, skip_preflight=args.skip_preflight)
    except RuntimeError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2

    n_failed = sum(1 for r in results if r.get("status") == "failed")
    return 1 if n_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
