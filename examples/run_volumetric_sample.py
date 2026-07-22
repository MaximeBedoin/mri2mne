"""Volumetric BEM route (Route C) end-to-end, via the public wrapper.

Real T1 -> FreeSurfer recon-all -autorecon1 + watershed (in WSL) -> 3-layer BEM
-> volume source space -> coregistration -> forward -> EEG -> inverse -> a volume
source estimate (-vl.stc).

Requires WSL2 with a licensed FreeSurfer 7.x (see the README "Route volumique").
The T1 and EEG here are the MNE sample subject (same subject), so the auditory
localisation is meaningful. The first run spends ~20 min in autorecon1; re-runs
skip it (outputs are cached).

Usage:
    python examples/run_volumetric_sample.py <sample_T1.nii.gz> <sample_eeg.edf> \
        <sample_montage.fif> <sample-eve.fif> [output_dir]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import mne  # noqa: E402
from mri2mne.wrapper import reconstruct_sources_volumetric  # noqa: E402
from mri2mne import wsl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("volsample")
mne.set_log_level("ERROR")


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    t1, edf, montage, events = (Path(a) for a in sys.argv[1:5])
    out = Path(sys.argv[5]) if len(sys.argv) > 5 else REPO / "examples" / "_vol_run"

    fs = wsl.check_freesurfer()
    log.info("FreeSurfer: %s", fs.describe())
    if not (fs.present and fs.has_license):
        log.error("A licensed FreeSurfer in WSL is required. See the README.")
        return 1

    result = reconstruct_sources_volumetric(
        subject="sampleVol",
        output_dir=out,
        t1_path=t1,                       # or dicom_dir=... for raw DICOM
        eeg_file=edf,
        digitization=montage,
        events=str(events),
        event_id={"aud_l": 1},
        tmin=-0.2, tmax=0.5, baseline=(None, 0.0),
        reject={"eeg": 150e-6},
        pos_mm=5.0,
        inverse_method="dSPM", snr=3.0,
    )

    log.info("")
    log.info("================= VOLUMETRIC RESULT =================")
    log.info("status:          %s", result.status)
    if result.error:
        log.info("error:           %s", result.error)
    log.info("forward:         %s", result.forward_file)
    log.info("source estimate: %s", result.source_estimate_file)
    if result.peak:
        log.info("peak: t=%.3f s, MRI (%.0f, %.0f, %.0f) mm",
                 result.peak["peak_time_s"], result.peak["peak_mri_x_mm"],
                 result.peak["peak_mri_y_mm"], result.peak["peak_mri_z_mm"])
    cr = result.metrics.get("coreg_residual_median_mm")
    if cr is not None:
        log.info("coreg residual:  %.2f mm", cr)
    log.info("====================================================")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
