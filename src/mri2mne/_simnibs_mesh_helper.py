"""Standalone helper (runs in simnibs_env) to extract coregistration inputs.

Pulls the scalp surface and the subject-space fiducials out of the SimNIBS head
model so the pipeline can coregister the digitised electrodes without any BEM
surface building. Everything is in mesh-world coordinates (subject scanner RAS),
which SimNIBS' MNE bridge treats as the "MRI" frame.

Imports only simnibs + numpy. Config via JSON on argv[1]:
    {"m2m_dir": ..., "out_scalp_npz": ..., "out_fiducials_json": ...}
"""

import glob
import json
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    import simnibs
    from simnibs.utils.csv_reader import read_csv_positions

    m2m = Path(cfg["m2m_dir"])
    mesh_files = list(m2m.glob("*.msh")) or list(m2m.glob("**/*.msh"))
    if not mesh_files:
        raise SystemExit(f"No .msh head model found in {m2m}")
    mesh = simnibs.read_msh(str(mesh_files[0]))

    # Scalp surface via SimNIBS' own crop_mesh (skin surface tag 1005). Not
    # necessarily a closed manifold, but ICP only needs surface points to fit
    # against. Triangle node indices are 1-based in the mesh; make them 0-based
    # and compact for a standalone surface.
    skin = mesh.crop_mesh(tags=[1005])
    tri = skin.elm.elm_type == 2
    faces = skin.elm.node_number_list[tri][:, :3] - 1
    used = np.unique(faces)
    remap = np.full(skin.nodes.nr, -1, np.int64)
    remap[used] = np.arange(len(used))
    rr_mm = skin.nodes.node_coord[used]          # mesh world, mm
    tris = remap[faces]
    np.savez(cfg["out_scalp_npz"], rr_mm=rr_mm, tris=tris)

    # Fiducials that charm warped into subject space, read with SimNIBS' public
    # csv reader (returns type, coords, extra, name, extra_cols, header).
    fids = {}
    fid_csv = glob.glob(str(m2m / "eeg_positions" / "Fiducials.csv"))
    if fid_csv:
        _types, coords, _extra, names, _cols, _hdr = read_csv_positions(fid_csv[0])
        alias = {"nz": "nasion", "nasion": "nasion", "lpa": "lpa", "rpa": "rpa"}
        for name, xyz in zip(names, np.asarray(coords, dtype=float)):
            key = alias.get(str(name).strip().lower())
            if key:
                fids[key] = [float(v) for v in xyz[:3]]
    Path(cfg["out_fiducials_json"]).write_text(json.dumps(fids), encoding="utf-8")

    print("MRI2MNE_RESULT " + json.dumps({
        "n_scalp_verts": int(len(rr_mm)),
        "n_scalp_tris": int(len(tris)),
        "fiducials": sorted(fids),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
