"""Logging that works under joblib's process pool.

Each worker writes to its own per-subject log file plus the shared console, so
a failed subject leaves a self-contained trace on disk.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s [%(subject)s] %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class _SubjectFilter(logging.Filter):
    """Inject a `subject` field so the console format never blows up."""

    def __init__(self, subject: str) -> None:
        super().__init__()
        self.subject = subject

    def filter(self, record: logging.LogRecord) -> bool:
        record.subject = getattr(record, "subject", self.subject)
        return True


def get_logger(subject: str, log_file: Path | None = None) -> logging.Logger:
    """Return a logger dedicated to `subject`.

    Handlers are attached once per logger name; calling this repeatedly for the
    same subject (as the resume logic does) will not duplicate output.
    """
    logger = logging.getLogger(f"mri2mne.{subject}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    console.addFilter(_SubjectFilter(subject))
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        file_handler.addFilter(_SubjectFilter(subject))
        logger.addHandler(file_handler)

    return logger
