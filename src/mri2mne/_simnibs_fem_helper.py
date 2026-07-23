"""Standalone helper that runs inside SimNIBS' own Python (simnibs_env).

The pipeline (in the mri2mne env) invokes this via subprocess because it needs
both `simnibs` and `mne`, which live together only in the SimNIBS environment.
It must therefore import nothing from the rest of mri2mne -- only simnibs, mne
and numpy.

Contract (all paths passed as JSON on argv[1]):
    {
      "m2m_dir": ...,          # charm output
      "fem_dir": ...,          # clean output dir for the leadfield
      "montage_csv": ...,      # where the SimNIBS montage CSV is written
      "info_fif": ...,         # mne Info/raw/evoked with the EEG channels
      "trans_fif": ...,        # head<->mri (mesh world) transform
      "out_fwd": ...,          # where to write -fwd.fif
      "out_src": ...,          # where to write -src.fif
      "subsampling": 10000,    # cortical source points per hemisphere (or null)
      "cpus": 4,
      "morph_to_fsaverage": 5  # or null
    }

The electrode montage is built with SimNIBS' own `prepare_montage`, which maps
the MNE head-coordinate electrodes into subject (mesh) space -- no bespoke
coordinate handling here. Prints a JSON result dict on the last stdout line.
"""

import json
import shutil
import sys
from pathlib import Path


def _shim_mne_for_simnibs(mne) -> None:
    """Restore MNE private-API names SimNIBS 4.6 expects at their old location.

    SimNIBS' eeg module calls `mne.source_space._complete_source_space_info`.
    In MNE >= 1.8 that function still exists but moved into the
    `mne.source_space._source_space` submodule and is no longer re-exported at
    the package level. We alias it back -- pointing at the same function, not
    reimplementing it -- so the SimNIBS->MNE bridge runs on current MNE.
    """
    # Newer MNE lazy-loads submodules, so the private ones SimNIBS reaches into
    # are not accessible until explicitly imported. Import them, then restore
    # the one name that also moved location. These point at the same functions
    # MNE still ships -- no behaviour is reimplemented.
    import importlib

    for sub in (
        "mne.source_space._source_space",
        "mne.forward._make_forward",
        "mne.forward._compute_forward",
        "mne.morph",
        "mne.transforms",
    ):
        importlib.import_module(sub)

    import mne.source_space

    if not hasattr(mne.source_space, "_complete_source_space_info"):
        from mne.source_space import _source_space as _ss

        mne.source_space._complete_source_space_info = _ss._complete_source_space_info


def main() -> int:
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    import mne
    import numpy as np

    _shim_mne_for_simnibs(mne)

    from simnibs.eeg import forward as sim_fwd
    from simnibs.eeg import utils_mne

    mne.set_log_level("ERROR")

    fem_dir = Path(cfg["fem_dir"])
    # SimNIBS refuses to overwrite an existing leadfield group in the hdf5, so
    # the FEM directory must be clean before every run.
    if fem_dir.exists():
        shutil.rmtree(fem_dir)
    fem_dir.mkdir(parents=True, exist_ok=True)

    # --- Montage: SimNIBS' own head->subject electrode transform -----------
    utils_mne.prepare_montage(cfg["montage_csv"], cfg["info_fif"], cfg["trans_fif"])

    # --- FEM leadfield (the slow part) -------------------------------------
    leadfield = sim_fwd.compute_tdcs_leadfield(
        cfg["m2m_dir"],
        str(fem_dir),
        cfg["montage_csv"],
        subsampling=cfg.get("subsampling"),
        point_electrodes=True,
        run_kwargs=dict(save_mat=False, cpus=int(cfg.get("cpus", 1))),
    )

    # --- Convert to an MNE forward -----------------------------------------
    info = mne.io.read_info(cfg["info_fif"])
    trans = mne.read_trans(cfg["trans_fif"])

    src, fwd, morph = sim_fwd.make_forward(
        cfg["m2m_dir"],
        leadfield,
        out_format="mne",
        info=info,
        trans=trans,
        morph_to_fsaverage=cfg.get("morph_to_fsaverage"),
        write=False,
    )

    # SimNIBS stores mri_head_t as head->MRI, but MNE's forward writer/reader
    # require MRI->head and do not invert on read (it raises "MRI/head
    # coordinate transformation not found"). Normalise the direction so the
    # written -fwd.fif re-reads in the pipeline environment.
    from mne.transforms import _ensure_trans

    mri_head_t = _ensure_trans(fwd["info"]["mri_head_t"], "mri", "head")
    with fwd["info"]._unlock():
        fwd["info"]["mri_head_t"] = mri_head_t
    fwd["mri_head_t"] = mri_head_t

    mne.write_forward_solution(cfg["out_fwd"], fwd, overwrite=True)
    mne.write_source_spaces(cfg["out_src"], src, overwrite=True)
    if morph is not None and cfg.get("out_morph"):
        morph.save(cfg["out_morph"], overwrite=True)

    gain = fwd["sol"]["data"]
    result = {
        "ok": bool(np.all(np.isfinite(gain))),
        "n_sources": int(fwd["nsource"]),
        "n_channels": int(fwd["nchan"]),
        "leadfield": str(leadfield),
        "src_type": src[0]["type"],
        "gain_max_abs": float(np.abs(gain).max()),
    }
    print("MRI2MNE_RESULT " + json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
