"""Command-line entry point for a source checkout (no install required).

    python run_pipeline.py --config config.yaml
    python run_pipeline.py --config config.yaml --subjects sub-001 sub-002
    python run_pipeline.py --config config.yaml --force headmodel coreg forward

This is a thin wrapper: it puts ``src/`` on the path and delegates to
``mri2mne.cli.main``. If the package is pip-installed, the same command is
available as ``mri2mne`` (see pyproject.toml).

The ``if __name__ == "__main__"`` guard below is load-bearing on Windows: joblib
spawns worker processes that re-import this module, and without the guard each
worker would relaunch the whole batch.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mri2mne.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
