"""Full end-to-end run through the public wrapper, using REAL charm output.

The definitive proof that the whole chain works: real T1 -> real SimNIBS charm
head model -> coregistration (mesh scalp + charm fiducials, MNE) -> SimNIBS FEM
leadfield -> mne.Forward on the cortical source space -> real EDF EEG ->
covariance -> inverse -> cortical source estimate (-lh/-rh.stc).

Only the DICOM->NIfTI step is bypassed (sample ships a T1, not DICOM); that
stage is validated separately. charm is run beforehand and its m2m output is
pre-placed so the wrapper's existence check skips re-running the 1.5 h segment.

Usage:
    python examples/run_full_pipeline_sample.py <path-to-m2m_sampleE2E>
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

import mne

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mri2mne.wrapper import reconstruct_sources  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("full")
mne.set_log_level("ERROR")

# Dossier Scripts de l'env conda simnibs_env (route FEM).
# >>> À REMPLACER par le chemin sur votre machine <<< (ou définir la variable
# d'environnement SIMNIBS_BIN). Typiquement <miniconda>/envs/simnibs_env/Scripts.
SIMNIBS_BIN = Path(
    os.environ.get(
        "SIMNIBS_BIN",
        r"C:/Users/VOTRE_NOM/Miniconda3/envs/simnibs_env/Scripts",
    )
)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_full_pipeline_sample.py <m2m_sampleE2E dir> [scratch dir]")
        return 2
    m2m_src = Path(sys.argv[1])
    scratch = Path(sys.argv[2]) if len(sys.argv) > 2 else m2m_src.parent
    if not (m2m_src / "final_tissues.nii.gz").is_file():
        print(f"charm output not found under {m2m_src}")
        return 2

    t1 = scratch / "sample_T1.nii.gz"
    edf = scratch / "sample_eeg.edf"
    montage = scratch / "sample_montage.fif"
    events = scratch / "sample-eve.fif"
    for f in (t1, edf, montage, events):
        if not f.is_file():
            print(f"missing fixture: {f}")
            return 2

    work = REPO / "examples" / "_full_run"
    if work.exists():
        shutil.rmtree(work)
    # Pre-place the real charm output where the wrapper expects m2m_<subject>,
    # so its existence check skips re-running the 1-2 h segmentation.
    m2m_dst = work / "sample" / "m2m_sample"
    m2m_dst.parent.mkdir(parents=True, exist_ok=True)
    log.info("Copying real charm output into place (%s)", m2m_dst)
    shutil.copytree(m2m_src, m2m_dst)
    # The pre-placed charm output was built with subid 'sampleE2E'; SimNIBS keys
    # the head mesh on the m2m folder's subid ('sample'). A real run never has
    # this mismatch (charm is run with the right id); rename for the demo.
    for msh in list(m2m_dst.glob("sampleE2E.msh*")):
        msh.rename(msh.with_name(msh.name.replace("sampleE2E", "sample")))

    log.info("=== reconstruct_sources (real charm output, real EDF EEG) ===")
    result = reconstruct_sources(
        subject="sample",
        output_dir=work,
        t1_path=t1,                       # DICOM step bypassed; T1 supplied
        eeg_file=edf,                     # REAL EDF reader path
        digitization=montage,            # electrode positions
        simnibs_bin_dir=SIMNIBS_BIN,     # charm + SimNIBS Python for the FEM
        fem_subsampling=5000,            # coarse cortical grid for a fast demo
        fem_cpus=1,                      # SimNIBS leadfield is serial on Windows
        morph_to_fsaverage=None,
        events=str(events),
        event_id={"aud_l": 1},
        tmin=-0.2, tmax=0.5, baseline=(None, 0.0),
        reject={"eeg": 150e-6},
        inverse_method="dSPM", snr=3.0,
    )

    log.info("")
    log.info("================= FULL PIPELINE RESULT =================")
    log.info("status:            %s", result.status)
    if result.error:
        log.info("error:             %s", result.error)
    log.info("forward:           %s", result.forward_file)
    log.info("inverse:           %s", result.inverse_file)
    log.info("source estimate:   %s", result.source_estimate_file)
    if result.peak:
        log.info("peak: t=%.3f s, MRI-RAS (%.0f, %.0f, %.0f) mm",
                 result.peak["peak_time_s"], result.peak["peak_mri_x_mm"],
                 result.peak["peak_mri_y_mm"], result.peak["peak_mri_z_mm"])
    cr = result.metrics.get("coreg_residual_median_mm")
    if cr is not None:
        log.info("coreg residual:    %.2f mm", cr)
    log.info("=======================================================")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
