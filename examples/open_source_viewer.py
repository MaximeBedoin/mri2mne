"""Open the interactive 3D source viewer for one processed subject.

The rotate-with-the-mouse MNE window with a time slider. Point it at the output
of a `reconstruct_sources` / batch run:

    python examples/open_source_viewer.py D:/derivatives patient01
    python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1

Under the hood it writes the SimNIBS cortical mesh in FreeSurfer format (once,
cached) and hands it to MNE's ordinary `stc.plot`, so everything MNE's Brain can
do -- rotate, zoom, scrub time, switch hemispheres -- is available.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import mne  # noqa: E402
from mri2mne.viz import block_on_viewer, open_viewer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output_dir", help="derivatives root passed to the pipeline")
    ap.add_argument("subject", help="subject id")
    ap.add_argument("--time", type=float, default=None,
                    help="initial time in seconds (default: the global peak)")
    ap.add_argument("--hemi", default="both", choices=["lh", "rh", "both", "split"])
    ap.add_argument("--surface", default="white")
    ap.add_argument("--subjects-dir", default=None,
                    help="override (default: <output_dir>/subjects)")
    args = ap.parse_args()

    mne.set_log_level("ERROR")
    mne.viz.set_3d_backend("pyvistaqt")

    brain = open_viewer(
        args.output_dir, args.subject,
        subjects_dir=args.subjects_dir,
        initial_time=args.time, hemi=args.hemi, surface=args.surface,
        time_viewer=True,
    )
    print("Interactive viewer open. Close the window to exit.")
    block_on_viewer()   # keep the window alive until the user closes it
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
