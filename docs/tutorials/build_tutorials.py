"""Generate the mri2mne HTML tutorials from one already-computed example run.

MNE-style tutorials: each pipeline stage is shown with the figure it produces
(T1, tissue segmentation, montage, EEG, evoked, coregistration, cortical
sources...). The figures are rendered once from the ``sample`` subject and the
pages are static HTML with relative image links -- they open locally and serve
unchanged from GitHub Pages, with no toolchain and nothing to recompute.

This script is the *rail*: every scientific figure is a plain MNE / matplotlib
call on outputs the pipeline already wrote. Run it only to regenerate the site.

    python docs/tutorials/build_tutorials.py --sample-dir <examples/_full_run/sample>

Bilingual (FR default, EN alongside). Content lives in PAGES below; keep the
``fr``/``en`` strings side by side so translations stay in sync.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Figure generation (offscreen; reuses the sample run's outputs)             #
# --------------------------------------------------------------------------- #

def _setup_offscreen():
    os.environ["PYVISTA_OFF_SCREEN"] = "true"
    os.environ.setdefault("MNE_3D_BACKEND", "pyvistaqt")


def generate_figures(sample: Path, raw_edf: Path, assets: Path) -> None:
    """Render every tutorial figure into ``assets`` from the sample outputs."""
    _setup_offscreen()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import nibabel as nib
    import mne
    import pyvista as pv
    from mne.transforms import apply_trans

    mne.set_log_level("ERROR")
    pv.OFF_SCREEN = True
    assets.mkdir(parents=True, exist_ok=True)

    mne_dir = sample / "mne"
    info = mne.io.read_info(str(mne_dir / "sample-fem-info.fif"))
    evoked = mne.read_evokeds(str(mne_dir / "sample-ave.fif"))[0]
    fwd = mne.read_forward_solution(str(mne_dir / "sample-fwd.fif"))
    trans = mne.read_trans(str(mne_dir / "sample-trans.fif"))

    # A scratch FreeSurfer-style subjects_dir so Brain / surfaces resolve. We
    # write the SimNIBS cortical mesh (carried in the forward's src) as
    # lh/rh.white, exactly as mri2mne.viz does at plot time.
    sd = assets / "_subjects"
    subj = sd / "sample"
    if subj.exists():
        shutil.rmtree(subj)
    (subj / "bem").mkdir(parents=True, exist_ok=True)
    shutil.copytree(sample.parent / "subjects" / "sample" / "bem",
                    subj / "bem", dirs_exist_ok=True)
    surf = subj / "surf"
    surf.mkdir(parents=True, exist_ok=True)
    for hemi, s in zip(("lh", "rh"), fwd["src"]):
        rr = np.asarray(s["rr"], float) * 1000.0
        tris = np.asarray(s["tris"], np.int32)
        for nm in ("white", "pial", "inflated"):
            mne.write_surface(str(surf / f"{hemi}.{nm}"), rr, tris, overwrite=True)
        try:
            import nibabel.freesurfer.io as fsio
            fsio.write_morph_data(str(surf / f"{hemi}.curv"),
                                  np.zeros(len(rr), np.float32))
        except Exception:
            pass

    def save(fig, name):
        fig.savefig(assets / name, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"  figure {name}")

    # 1. T1 orthoslices ------------------------------------------------------
    d = nib.load(str(sample / "anat" / "sample_T1w.nii.gz")).get_fdata()
    c = [s // 2 for s in d.shape]
    fig, ax = plt.subplots(1, 3, figsize=(10, 3.6))
    for a, sl in zip(ax, (d[c[0], :, :], d[:, c[1], :], d[:, :, c[2]])):
        a.imshow(np.rot90(sl), cmap="gray"); a.axis("off")
    fig.tight_layout(); save(fig, "t1_ortho.png")

    # 2. Tissue segmentation (charm) ----------------------------------------
    seg = nib.load(str(sample / "m2m_sample" / "final_tissues.nii.gz")).get_fdata()
    if seg.ndim == 4:
        seg = seg[..., 0]
    segm = np.ma.masked_where(seg == 0, seg)
    fig, ax = plt.subplots(1, 3, figsize=(10, 3.6))
    planes = [(d[c[0], :, :], segm[c[0], :, :]), (d[:, c[1], :], segm[:, c[1], :]),
              (d[:, :, c[2]], segm[:, :, c[2]])]
    for a, (bg, ov) in zip(ax, planes):
        a.imshow(np.rot90(bg), cmap="gray")
        a.imshow(np.rot90(ov), cmap="tab10", alpha=0.5, vmin=0, vmax=10)
        a.axis("off")
    fig.tight_layout(); save(fig, "tissues.png")

    # 3. Electrode montage (2D) ---------------------------------------------
    fig = mne.viz.plot_sensors(info, show_names=False, show=False)
    save(fig, "montage2d.png")

    # 4. Raw EEG -------------------------------------------------------------
    mne.viz.set_browser_backend("matplotlib")
    raw = mne.io.read_raw_edf(str(raw_edf), preload=True)
    raw.pick("eeg").filter(1, 40)
    fig = raw.plot(duration=8, n_channels=15, show=False, scalings="auto")
    save(fig, "raw_eeg.png")

    # 5. Evoked butterfly + topomap -----------------------------------------
    save(evoked.plot(spatial_colors=True, show=False), "evoked_butterfly.png")
    peak_t = evoked.get_peak()[1]
    save(evoked.plot_topomap(times=[peak_t], show=False), "evoked_topomap.png")

    # 6. Coregistration: head surface + electrodes (manual pyvista) ---------
    head = mne.read_bem_surfaces(str(subj / "bem" / "sample-head.fif"))[0]
    rr = head["rr"] * 1000.0
    faces = np.hstack([np.full((len(head["tris"]), 1), 3),
                       head["tris"]]).astype(np.int64).ravel()
    picks = mne.pick_types(info, eeg=True)
    loc = np.array([info["chs"][i]["loc"][:3] for i in picks])
    loc_mri = apply_trans(trans, loc) * 1000.0
    pl = pv.Plotter(off_screen=True, window_size=(1000, 850))
    pl.set_background("white")
    pl.add_mesh(pv.PolyData(rr, faces), color="#f2d6c2", opacity=0.5,
                smooth_shading=True, specular=0.2)
    pl.add_mesh(pv.PolyData(loc_mri).glyph(geom=pv.Sphere(radius=4)),
                color="#cc3311")
    pl.camera_position = "yz"; pl.camera.azimuth = 20; pl.camera.elevation = 15
    pl.reset_camera(); pl.render()
    plt.imsave(str(assets / "coreg3d.png"), pl.screenshot()); pl.close()
    print("  figure coreg3d.png")

    # 7. Source space: cortex + source points --------------------------------
    pl = pv.Plotter(off_screen=True, window_size=(1000, 850))
    pl.set_background("white")
    allpts = []
    for s in fwd["src"]:
        r = np.asarray(s["rr"], float) * 1000.0
        f = np.hstack([np.full((len(s["tris"]), 1), 3),
                       s["tris"]]).astype(np.int64).ravel()
        pl.add_mesh(pv.PolyData(r, f), color="#d9d9d9", opacity=1.0,
                    smooth_shading=True)
        allpts.append(r[s["vertno"]])
    pts = np.concatenate(allpts)[::7]
    pl.add_mesh(pv.PolyData(pts).glyph(geom=pv.Sphere(radius=1.6)),
                color="#3366aa")
    pl.camera_position = "xz"; pl.camera.azimuth = 20; pl.camera.elevation = 10
    pl.reset_camera(); pl.render()
    plt.imsave(str(assets / "source_space.png"), pl.screenshot()); pl.close()
    print("  figure source_space.png")

    # 8. Cortical source estimate at the peak --------------------------------
    stc = mne.read_source_estimate(str(mne_dir / "sample"), subject="sample")
    ptime = stc.get_peak(vert_as_index=False, time_as_index=False)[1]
    brain = stc.plot(subject="sample", subjects_dir=str(sd), surface="white",
                     hemi="both", initial_time=ptime, time_viewer=False,
                     show_traces=False, background="white", size=(950, 620),
                     clim=dict(kind="percent", lims=[90, 97, 99.9]),
                     colormap="hot")
    shots = []
    for v in ("lateral", "medial"):
        brain.show_view(v, hemi="lh"); shots.append(np.asarray(brain.screenshot()))
    brain.close()
    fig, ax = plt.subplots(1, 2, figsize=(10, 5))
    for a, sh, v in zip(ax, shots, ("lateral", "medial")):
        a.imshow(sh); a.set_title(v, fontsize=11); a.axis("off")
    fig.suptitle(f"dSPM @ {ptime * 1000:.0f} ms", fontsize=13)
    fig.tight_layout(); save(fig, "sources_brain.png")

    # 9. Peak source time course --------------------------------------------
    vidx, t = stc.get_peak(vert_as_index=True, time_as_index=False)
    fig, a = plt.subplots(figsize=(7, 3.2))
    a.plot(stc.times * 1000, stc.data[vidx], color="#cc3311", lw=2)
    a.axvline(t * 1000, color="k", ls="--", lw=1)
    a.set_xlabel("Time (ms)"); a.set_ylabel("dSPM amplitude")
    a.set_title("Peak source time course")
    fig.tight_layout(); save(fig, "source_timecourse.png")

    shutil.rmtree(sd, ignore_errors=True)  # scratch surfaces, not shipped


def generate_volumetric_figures(vol: Path, subjects_dir: Path,
                                assets: Path) -> None:
    """Render the volumetric-route figures from a computed BEM/FreeSurfer run.

    ``vol`` is the subject derivatives folder (…/sampleW); ``subjects_dir`` is
    the FreeSurfer-style subjects dir holding ``<subject>/bem`` and
    ``<subject>/mri/T1.mgz``. The subject id is read from ``vol.name``.
    """
    _setup_offscreen()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import mne
    from mne.transforms import apply_trans
    import pyvista as pv

    mne.set_log_level("ERROR")
    pv.OFF_SCREEN = True
    assets.mkdir(parents=True, exist_ok=True)

    subj = vol.name
    mne_dir = vol / "mne"
    src = mne.read_source_spaces(str(mne_dir / f"{subj}-vol-src.fif"))
    stc = mne.read_source_estimate(str(mne_dir / f"{subj}-vol-vl.stc"))
    trans = mne.read_trans(str(mne_dir / f"{subj}-trans.fif"))
    info = mne.io.read_info(str(mne_dir / f"{subj}-ave.fif"))

    # 1. Three-layer BEM over the T1 (the canonical mne.viz.plot_bem figure)
    fig = mne.viz.plot_bem(subject=subj, subjects_dir=str(subjects_dir),
                           orientation="coronal", slices=[70, 100, 130, 160],
                           show=False)
    fig.savefig(assets / "vol_bem.png", dpi=120, bbox_inches="tight")
    plt.close(fig); print("  figure vol_bem.png")

    # 2. Volume source grid inside the inner skull
    fig = mne.viz.plot_bem(subject=subj, subjects_dir=str(subjects_dir),
                           orientation="coronal", slices=[80, 110, 140],
                           src=src, show=False)
    fig.savefig(assets / "vol_source_space.png", dpi=120, bbox_inches="tight")
    plt.close(fig); print("  figure vol_source_space.png")

    # 3. Coregistration: electrodes on the FreeSurfer scalp (outer_skin)
    rr, tris = mne.read_surface(str(subjects_dir / subj / "bem" / "outer_skin.surf"))
    faces = np.hstack([np.full((len(tris), 1), 3), tris]).astype(np.int64).ravel()
    picks = mne.pick_types(info, eeg=True)
    loc = np.array([info["chs"][i]["loc"][:3] for i in picks])
    loc_mri = apply_trans(trans, loc) * 1000.0
    pl = pv.Plotter(off_screen=True, window_size=(1000, 850))
    pl.set_background("white")
    pl.add_mesh(pv.PolyData(rr, faces), color="#f2d6c2", opacity=0.5,
                smooth_shading=True, specular=0.2)
    pl.add_mesh(pv.PolyData(loc_mri).glyph(geom=pv.Sphere(radius=4)), color="#cc3311")
    pl.camera_position = "yz"; pl.camera.azimuth = 20; pl.camera.elevation = 15
    pl.reset_camera(); pl.render()
    plt.imsave(str(assets / "vol_coreg.png"), pl.screenshot()); pl.close()
    print("  figure vol_coreg.png")

    # 4. Volume source estimate as a stat map on the T1 (nilearn)
    from nilearn import plotting
    from nilearn.image import index_img
    _, tidx = stc.get_peak(vert_as_index=True, time_as_index=True)
    img3d = index_img(stc.as_volume(src, mri_resolution=False), tidx)
    disp = plotting.plot_stat_map(
        img3d, bg_img=str(subjects_dir / subj / "mri" / "T1.mgz"),
        display_mode="ortho", colorbar=True, title="dSPM (volume) at peak",
        threshold=float(np.percentile(np.abs(stc.data), 99.5)))
    disp.savefig(str(assets / "vol_sources.png"), dpi=140); disp.close()
    print("  figure vol_sources.png")

    # 5. Peak source time course
    vidx, t = stc.get_peak(vert_as_index=True, time_as_index=False)
    fig, a = plt.subplots(figsize=(7, 3.2))
    a.plot(stc.times * 1000, stc.data[vidx], color="#3366aa", lw=2)
    a.axvline(t * 1000, color="k", ls="--", lw=1)
    a.set_xlabel("Time (ms)"); a.set_ylabel("dSPM amplitude")
    a.set_title("Peak source time course (volume)")
    fig.tight_layout()
    fig.savefig(assets / "vol_timecourse.png", dpi=120, bbox_inches="tight")
    plt.close(fig); print("  figure vol_timecourse.png")


# --------------------------------------------------------------------------- #
#  Minimal Python syntax highlighting                                         #
# --------------------------------------------------------------------------- #

_KW = {"from", "import", "as", "def", "return", "None", "True", "False", "for",
       "in", "if", "else", "elif", "with", "not", "and", "or", "while", "class",
       "try", "except", "lambda", "yield", "pass", "raise"}
_TOKEN = re.compile(
    r"(#[^\n]*)"
    r"|(\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"[^\"\n]*\"|'[^'\n]*')"
    r"|(\b\d+\.?\d*\b)"
    r"|(\b[A-Za-z_]\w*\b)"
)


def highlight(code: str) -> str:
    out, i = [], 0
    for m in _TOKEN.finditer(code):
        if m.start() > i:
            out.append(html.escape(code[i:m.start()]))
        comment, string, number, name = m.groups()
        if comment is not None:
            out.append(f'<span class="cm">{html.escape(comment)}</span>')
        elif string is not None:
            out.append(f'<span class="st">{html.escape(string)}</span>')
        elif number is not None:
            out.append(f'<span class="nu">{number}</span>')
        else:
            cls = "kw" if name in _KW else "nm"
            out.append(f'<span class="{cls}">{name}</span>')
        i = m.end()
    out.append(html.escape(code[i:]))
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Page content (data-driven, bilingual)                                      #
# --------------------------------------------------------------------------- #
# Block tuples: ("h2"|"h3"|"p"|"note", {fr, en}) / ("code", str) /
#               ("fig", name, {fr, en})

def _t(fr, en):
    return {"fr": fr, "en": en}


PAGES = [
    {
        "id": "01_end_to_end",
        "order": 1,
        "title": _t("Du DICOM aux sources : le pipeline complet",
                    "From DICOM to sources: the complete pipeline"),
        "lead": _t(
            "Le parcours nominal : une IRM DICOM et un EEG entrent, une estimation "
            "de sources corticales sort. On visualise chaque étape sur le sujet "
            "d'exemple <code>sample</code>.",
            "The nominal run: a DICOM MRI and an EEG go in, a cortical source "
            "estimate comes out. We visualise every stage on the <code>sample</code> "
            "example subject."),
        "blocks": [
            ("note", _t(
                "Toutes les figures de cette page ont été produites par le pipeline "
                "sur le sujet <code>sample</code> livré avec le projet. Rien à "
                "recalculer pour lire le tutoriel.",
                "Every figure on this page was produced by the pipeline on the "
                "<code>sample</code> subject shipped with the project. Nothing to "
                "recompute in order to read the tutorial.")),

            ("h2", _t("L'appel unique", "The single call")),
            ("p", _t(
                "Tout le pipeline de surface (route FEM SimNIBS, native Windows) "
                "tient dans un appel. Chaque argument correspond à une étape "
                "détaillée plus bas.",
                "The whole surface pipeline (SimNIBS FEM route, Windows-native) "
                "fits in one call. Each argument maps to a stage detailed below.")),
            ("code", _t(
             'from mri2mne.wrapper import reconstruct_sources\n\n'
             'result = reconstruct_sources(\n'
             '    subject="sample",\n'
             '    output_dir="D:/derivatives",\n'
             '    dicom_dir="D:/dicom/sample",         # IRM : un dossier DICOM\n'
             '    eeg_file="D:/eeg/sample.edf",        # EEG a localiser\n'
             '    digitization="D:/dig/sample.elc",    # positions des electrodes\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    events="find", event_id={"aud_l": 1},\n'
             '    tmin=-0.2, tmax=0.5, baseline=(None, 0.0),\n'
             '    inverse_method="dSPM", snr=3.0,\n'
             ')\n'
             'print(result.source_estimate_file, result.peak)',
             'from mri2mne.wrapper import reconstruct_sources\n\n'
             'result = reconstruct_sources(\n'
             '    subject="sample",\n'
             '    output_dir="D:/derivatives",\n'
             '    dicom_dir="D:/dicom/sample",         # MRI: a DICOM folder\n'
             '    eeg_file="D:/eeg/sample.edf",        # EEG to localise\n'
             '    digitization="D:/dig/sample.elc",    # electrode positions\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    events="find", event_id={"aud_l": 1},\n'
             '    tmin=-0.2, tmax=0.5, baseline=(None, 0.0),\n'
             '    inverse_method="dSPM", snr=3.0,\n'
             ')\n'
             'print(result.source_estimate_file, result.peak)')),

            ("h2", _t("Étape 1 — L'anatomie (DICOM → T1)",
                      "Step 1 — Anatomy (DICOM → T1)")),
            ("p", _t(
                "Le dossier DICOM est anonymisé puis converti en un unique volume "
                "T1 NIfTI. C'est la seule image dont le reste du pipeline a besoin.",
                "The DICOM folder is anonymised then converted to a single T1 "
                "NIfTI volume. That image is all the rest of the pipeline needs.")),
            ("fig", "t1_ortho.png", _t(
                "Le T1 du sujet <code>sample</code>, coupes sagittale, coronale et "
                "axiale.",
                "The <code>sample</code> subject's T1, sagittal, coronal and axial "
                "slices.")),

            ("h2", _t("Étape 2 — Le modèle de tête (SimNIBS charm)",
                      "Step 2 — The head model (SimNIBS charm)")),
            ("p", _t(
                "<code>charm</code> segmente le T1 en tissus (matière grise et "
                "blanche, LCR, crâne, scalp…) et en construit un maillage. C'est "
                "l'étape longue (~1–2 h) et le cœur de la physique : la conduction "
                "du courant dépend de cette anatomie.",
                "<code>charm</code> segments the T1 into tissues (grey and white "
                "matter, CSF, skull, scalp…) and builds a mesh from them. This is "
                "the long step (~1–2 h) and the core of the physics: current "
                "conduction depends on this anatomy.")),
            ("fig", "tissues.png", _t(
                "Segmentation en tissus superposée au T1. Chaque couleur est une "
                "classe de conductivité du modèle FEM.",
                "Tissue segmentation overlaid on the T1. Each colour is a "
                "conductivity class of the FEM model.")),

            ("h2", _t("Étape 3 — Électrodes et signal EEG",
                      "Step 3 — Electrodes and EEG signal")),
            ("p", _t(
                "Les positions d'électrodes viennent de la digitisation (l'EDF n'en "
                "contient pas). Leurs libellés doivent correspondre aux canaux de "
                "l'EEG ; les écarts sont signalés, pas ignorés.",
                "Electrode positions come from the digitisation (EDF stores none). "
                "Their labels must match the EEG channels; mismatches are reported, "
                "not silently dropped.")),
            ("fig", "montage2d.png", _t(
                "Disposition 2D des électrodes lues depuis la digitisation.",
                "2D layout of the electrodes read from the digitisation.")),
            ("p", _t(
                "Le signal continu est lu puis filtré (par défaut 1–40 Hz) et "
                "re-référencé en moyenne commune.",
                "The continuous recording is read, then band-pass filtered "
                "(1–40 Hz by default) and set to an average reference.")),
            ("fig", "raw_eeg.png", _t(
                "Extrait de l'EEG continu après filtrage.",
                "A segment of the continuous EEG after filtering.")),

            ("h2", _t("Étape 4 — La réponse évoquée",
                      "Step 4 — The evoked response")),
            ("p", _t(
                "Les événements découpent le signal en époques, moyennées en une "
                "réponse évoquée. C'est elle qu'on localise. La covariance du bruit "
                "est estimée sur la ligne de base pré-stimulus.",
                "Events cut the signal into epochs, averaged into an evoked "
                "response. That is what gets localised. The noise covariance is "
                "estimated from the pre-stimulus baseline.")),
            ("fig", "evoked_butterfly.png", _t(
                "Réponse évoquée, toutes électrodes superposées (« butterfly »).",
                "Evoked response, all electrodes overlaid (butterfly plot).")),
            ("fig", "evoked_topomap.png", _t(
                "Topographie du potentiel au pic de la réponse.",
                "Scalp topography of the potential at the response peak.")),

            ("h2", _t("Étape 5 — La coregistration",
                      "Step 5 — Coregistration")),
            ("p", _t(
                "On aligne les électrodes sur le scalp issu du maillage (ICP). "
                "C'est le point le plus sensible : une pose fausse déplace les "
                "sources sans rien casser en aval, donc le résidu est mesuré et "
                "figuré pour contrôle visuel.",
                "The electrodes are aligned to the mesh-derived scalp (ICP). This "
                "is the most sensitive point: a wrong pose shifts the sources "
                "without breaking anything downstream, so the residual is measured "
                "and plotted for a visual check.")),
            ("fig", "coreg3d.png", _t(
                "Électrodes (rouge) posées sur la surface de tête du sujet après "
                "coregistration.",
                "Electrodes (red) sitting on the subject's head surface after "
                "coregistration.")),

            ("h2", _t("Étape 6 — Le modèle direct (forward)",
                      "Step 6 — The forward model")),
            ("p", _t(
                "SimNIBS résout le problème direct par éléments finis : pour chaque "
                "point source du cortex, quel potentiel à chaque électrode. "
                "L'espace des sources est la surface corticale centrale.",
                "SimNIBS solves the forward problem by finite elements: for each "
                "cortical source point, the potential at each electrode. The source "
                "space is the central cortical surface.")),
            ("fig", "source_space.png", _t(
                "Espace des sources : points (bleu) répartis sur la surface "
                "corticale (un sur sept affiché).",
                "Source space: points (blue) spread over the cortical surface (one "
                "in seven shown).")),

            ("h2", _t("Étape 7 — L'inverse et les sources",
                      "Step 7 — Inverse and sources")),
            ("p", _t(
                "Forward, covariance et EEG se combinent en un opérateur inverse "
                "(norme minimale : dSPM ici), appliqué à la réponse évoquée pour "
                "obtenir l'estimation de sources sur le cortex.",
                "Forward, covariance and EEG combine into an inverse operator "
                "(minimum-norm: dSPM here), applied to the evoked response to yield "
                "the source estimate on the cortex.")),
            ("fig", "sources_brain.png", _t(
                "Estimation dSPM au pic, hémisphère gauche, vues latérale et "
                "médiale.",
                "dSPM estimate at the peak, left hemisphere, lateral and medial "
                "views.")),
            ("fig", "source_timecourse.png", _t(
                "Décours temporel de la source la plus forte.",
                "Time course of the strongest source.")),
            ("p", _t(
                "<code>result.peak</code> donne la position du maximum en "
                "millimètres (repère IRM) et son instant — souvent le livrable "
                "clinique. Un rapport QC HTML est aussi écrit par sujet.",
                "<code>result.peak</code> gives the location of the maximum in "
                "millimetres (MRI frame) and its latency — often the clinical "
                "deliverable. A per-subject HTML QC report is written as well.")),

            ("h2", _t("Et ensuite", "Where to go next")),
            ("p", _t(
                "Les scénarios suivants ne changent que quelques arguments de ce "
                "même appel : EEG déjà préprocessé, fichier d'événements externe, "
                "ou départ d'un T1 sans DICOM.",
                "The scenarios that follow change only a few arguments of this same "
                "call: already-preprocessed EEG, an external events file, or "
                "starting from a T1 without DICOM.")),
        ],
    },

    {
        "id": "02_preprocessed_eeg",
        "order": 2,
        "title": _t("EEG déjà préprocessé", "EEG already preprocessed"),
        "lead": _t(
            "Votre EEG est déjà filtré et référencé (par ex. sorti d'un pipeline "
            "maison ou de MNE) ? Il faut empêcher le pipeline de le refaire.",
            "Your EEG is already filtered and referenced (e.g. from your own "
            "pipeline or from MNE)? You must stop the pipeline from doing it again."),
        "blocks": [
            ("h2", _t("Le principe", "The idea")),
            ("p", _t(
                "Refiltrer un signal déjà filtré déforme les basses fréquences et "
                "fausse la covariance ; re-référencer deux fois est une erreur "
                "silencieuse. On neutralise les deux étapes.",
                "Re-filtering an already-filtered signal distorts the low "
                "frequencies and biases the covariance; re-referencing twice is a "
                "silent error. We switch both steps off.")),
            ("h2", _t("Les arguments", "The arguments")),
            ("p", _t(
                "Mettre <code>l_freq</code> et <code>h_freq</code> à "
                "<code>None</code> désactive le filtrage ; "
                "<code>eeg_reference=None</code> conserve votre référence.",
                "Set <code>l_freq</code> and <code>h_freq</code> to "
                "<code>None</code> to disable filtering; "
                "<code>eeg_reference=None</code> keeps your existing reference.")),
            ("code", _t(
             'result = reconstruct_sources(\n'
             '    subject="sample",\n'
             '    output_dir="D:/derivatives",\n'
             '    t1_path="D:/anat/sample_T1w.nii.gz",\n'
             '    eeg_file="D:/eeg/sample_clean.fif",   # deja preprocesse\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    l_freq=None, h_freq=None,             # <- pas de refiltrage\n'
             '    eeg_reference=None,                   # <- garder la reference\n'
             '    events="find", event_id={"aud_l": 1},\n'
             ')',
             'result = reconstruct_sources(\n'
             '    subject="sample",\n'
             '    output_dir="D:/derivatives",\n'
             '    t1_path="D:/anat/sample_T1w.nii.gz",\n'
             '    eeg_file="D:/eeg/sample_clean.fif",   # already preprocessed\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    l_freq=None, h_freq=None,             # <- no re-filtering\n'
             '    eeg_reference=None,                   # <- keep the reference\n'
             '    events="find", event_id={"aud_l": 1},\n'
             ')')),
            ("note", _t(
                "Si vous avez seulement filtré (sans re-référencer), gardez "
                "<code>eeg_reference=\"average\"</code>. La référence moyenne "
                "commune, exprimée comme projection, est recommandée pour la "
                "modélisation de sources.",
                "If you only filtered (without re-referencing), keep "
                "<code>eeg_reference=\"average\"</code>. An average reference, "
                "applied as a projection, is recommended for source modelling.")),
            ("p", _t(
                "Le reste est identique au tutoriel complet : la réponse évoquée et "
                "les sources se calculent de la même façon.",
                "Everything else matches the full tutorial: the evoked response and "
                "the sources are computed the same way.")),
            ("fig", "evoked_butterfly.png", _t(
                "La réponse évoquée obtenue à partir de l'EEG fourni.",
                "The evoked response obtained from the supplied EEG.")),
        ],
    },

    {
        "id": "03_external_events",
        "order": 3,
        "title": _t("Événements dans un fichier externe",
                    "Events in an external file"),
        "lead": _t(
            "Vos marqueurs ne sont pas dans l'EEG mais dans un fichier à part "
            "(par ex. un <code>-eve.fif</code> MNE, ou un tableau que vous "
            "construisez). Voici comment les fournir.",
            "Your triggers are not in the EEG but in a separate file (e.g. an MNE "
            "<code>-eve.fif</code>, or an array you build). Here is how to pass "
            "them."),
        "blocks": [
            ("h2", _t("Trois façons de fournir les événements",
                      "Three ways to pass events")),
            ("p", _t(
                "L'argument <code>events</code> accepte un chemin, le mot-clé "
                "<code>\"find\"</code>, ou un tableau NumPy déjà en mémoire.",
                "The <code>events</code> argument accepts a path, the keyword "
                "<code>\"find\"</code>, or a NumPy array already in memory.")),
            ("h3", _t("1. Un fichier MNE <code>-eve.fif</code>",
                      "1. An MNE <code>-eve.fif</code> file")),
            ("code", _t(
             'result = reconstruct_sources(\n'
             '    subject="sample", output_dir="D:/derivatives",\n'
             '    t1_path="D:/anat/sample_T1w.nii.gz",\n'
             '    eeg_file="D:/eeg/sample.edf",\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    events="D:/eeg/sample-eve.fif",       # <- fichier externe\n'
             '    event_id={"aud_l": 1, "aud_r": 2},    # conditions a garder\n'
             '    tmin=-0.2, tmax=0.5,\n'
             ')',
             'result = reconstruct_sources(\n'
             '    subject="sample", output_dir="D:/derivatives",\n'
             '    t1_path="D:/anat/sample_T1w.nii.gz",\n'
             '    eeg_file="D:/eeg/sample.edf",\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    events="D:/eeg/sample-eve.fif",       # <- external file\n'
             '    event_id={"aud_l": 1, "aud_r": 2},    # conditions to keep\n'
             '    tmin=-0.2, tmax=0.5,\n'
             ')')),
            ("p", _t(
                "Le fichier suit le format MNE : trois colonnes (échantillon, "
                "valeur précédente, code). <code>event_id</code> choisit les codes "
                "à épocher et les nomme.",
                "The file follows the MNE format: three columns (sample, previous "
                "value, code). <code>event_id</code> selects which codes to epoch "
                "and names them.")),
            ("h3", _t("2. Détection depuis la voie trigger",
                      "2. Detection from the trigger channel")),
            ("p", _t(
                "Si les impulsions sont sur une voie de stimulation dans l'EEG, "
                "<code>\"find\"</code> appelle <code>mne.find_events</code>.",
                "If the pulses are on a stim channel inside the EEG, "
                "<code>\"find\"</code> calls <code>mne.find_events</code>.")),
            ("code", 'events="find", event_id={"aud_l": 1}'),
            ("h3", _t("3. Un tableau construit à la main",
                      "3. A hand-built array")),
            ("p", _t(
                "Utile quand les temps viennent d'un journal comportemental. "
                "Colonnes : échantillon, 0, code.",
                "Useful when the times come from a behavioural log. Columns: "
                "sample, 0, code.")),
            ("code",
             'import numpy as np\n'
             'events = np.array([[500, 0, 1],\n'
             '                   [1200, 0, 1],\n'
             '                   [2100, 0, 2]])\n'
             'reconstruct_sources(..., events=events, event_id={"aud_l": 1, "aud_r": 2})'),
            ("note", _t(
                "Sans aucun événement (<code>events=None</code>), tout "
                "l'enregistrement est traité comme une seule époque — pratique pour "
                "localiser une réponse déjà moyennée ou un segment découpé à la "
                "main (voir le scénario correspondant).",
                "With no events at all (<code>events=None</code>), the whole "
                "recording is treated as a single epoch — handy to localise an "
                "already-averaged response or a hand-cut segment (see that "
                "scenario).")),
            ("fig", "evoked_topomap.png", _t(
                "Topographie au pic, une fois les époques moyennées.",
                "Peak topography once the epochs are averaged.")),
        ],
    },

    {
        "id": "04_t1_no_dicom",
        "order": 4,
        "title": _t("Partir d'un T1, sans DICOM",
                    "Start from a T1, without DICOM"),
        "lead": _t(
            "Vous avez déjà un T1 en NIfTI (dé-identifié, ou issu d'un autre "
            "logiciel) et pas les DICOM d'origine. Le pipeline part directement de "
            "cette image.",
            "You already have a T1 as NIfTI (de-identified, or from another tool) "
            "and not the original DICOM. The pipeline starts straight from that "
            "image."),
        "blocks": [
            ("h2", _t("Un seul argument change", "Only one argument changes")),
            ("p", _t(
                "On donne <code>t1_path</code> au lieu de <code>dicom_dir</code>. "
                "Exactement un des deux est requis — fournir les deux (ou aucun) "
                "lève une erreur immédiate.",
                "Pass <code>t1_path</code> instead of <code>dicom_dir</code>. "
                "Exactly one of the two is required — passing both (or neither) "
                "raises an immediate error.")),
            ("code", _t(
             'result = reconstruct_sources(\n'
             '    subject="sample", output_dir="D:/derivatives",\n'
             '    t1_path="D:/anat/sample_T1w.nii.gz",  # <- au lieu de dicom_dir\n'
             '    eeg_file="D:/eeg/sample.edf",\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    events="find", event_id={"aud_l": 1},\n'
             ')',
             'result = reconstruct_sources(\n'
             '    subject="sample", output_dir="D:/derivatives",\n'
             '    t1_path="D:/anat/sample_T1w.nii.gz",  # <- instead of dicom_dir\n'
             '    eeg_file="D:/eeg/sample.edf",\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    simnibs_bin_dir="C:/Users/me/SimNIBS-4.5/bin",\n'
             '    events="find", event_id={"aud_l": 1},\n'
             ')')),
            ("p", _t(
                "La conversion DICOM→NIfTI est simplement sautée ; le T1 est copié "
                "tel quel et alimente <code>charm</code>. Toutes les étapes "
                "suivantes sont identiques.",
                "The DICOM→NIfTI conversion is simply skipped; the T1 is copied as "
                "is and feeds <code>charm</code>. Every later stage is identical.")),
            ("fig", "t1_ortho.png", _t(
                "Le T1 fourni, tel qu'utilisé pour la segmentation.",
                "The supplied T1, as used for segmentation.")),
            ("note", _t(
                "Un T2 (<code>t2_path</code>) améliore nettement la segmentation du "
                "crâne si votre protocole en comporte un. L'anonymisation DICOM "
                "n'a plus lieu d'être ici — assurez-vous que le T1 est déjà "
                "dé-identifié avant de le partager.",
                "A T2 (<code>t2_path</code>) markedly improves skull segmentation "
                "if your protocol has one. DICOM anonymisation no longer applies "
                "here — make sure the T1 is already de-identified before sharing "
                "it.")),
        ],
    },

    {
        "id": "05_volumetric",
        "order": 5,
        "title": _t("Route volumique (BEM / FreeSurfer) : le pipeline complet",
                    "Volumetric route (BEM / FreeSurfer): the complete pipeline"),
        "lead": _t(
            "L'alternative à la route corticale : FreeSurfer (via WSL) → BEM à "
            "trois couches → espace de sources <strong>volumique</strong> → "
            "estimation de sources dans tout le volume cérébral. Mêmes entrées, "
            "un maillage de tête différent.",
            "The alternative to the cortical route: FreeSurfer (via WSL) → "
            "three-layer BEM → <strong>volumetric</strong> source space → a source "
            "estimate throughout the brain volume. Same inputs, a different head "
            "model."),
        "blocks": [
            ("note", _t(
                "Figures produites par le pipeline volumique sur le sujet "
                "<code>sampleW</code> (même IRM que le tutoriel corticale). Cette "
                "route requiert <strong>WSL2 + FreeSurfer</strong> ; la partie EEG "
                "est identique au tutoriel corticale.",
                "Figures produced by the volumetric pipeline on the "
                "<code>sampleW</code> subject (same MRI as the cortical tutorial). "
                "This route requires <strong>WSL2 + FreeSurfer</strong>; the EEG "
                "half is identical to the cortical tutorial.")),

            ("h2", _t("Corticale ou volumique ?", "Cortical or volumetric?")),
            ("p", _t(
                "La route corticale (FEM SimNIBS, native Windows) contraint les "
                "sources à la surface du cortex. La route volumique remplit tout "
                "le volume cérébral d'une grille régulière — utile pour des sources "
                "profondes ou sous-corticales — au prix de FreeSurfer sous WSL et "
                "d'un modèle BEM à trois couches.",
                "The cortical route (SimNIBS FEM, Windows-native) constrains "
                "sources to the cortical surface. The volumetric route fills the "
                "whole brain volume with a regular grid — useful for deep or "
                "subcortical sources — at the cost of FreeSurfer under WSL and a "
                "three-layer BEM model.")),

            ("h2", _t("L'appel unique", "The single call")),
            ("p", _t(
                "Une fonction distincte, <code>reconstruct_sources_volumetric</code>, "
                "avec les arguments propres à FreeSurfer et au BEM.",
                "A separate function, "
                "<code>reconstruct_sources_volumetric</code>, with the arguments "
                "specific to FreeSurfer and the BEM.")),
            ("code", _t(
             'from mri2mne.wrapper import reconstruct_sources_volumetric\n\n'
             'result = reconstruct_sources_volumetric(\n'
             '    subject="sampleW",\n'
             '    output_dir="D:/derivatives",\n'
             '    dicom_dir="D:/dicom/sample",          # ou t1_path=...\n'
             '    eeg_file="D:/eeg/sample.edf",\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    wsl_distro="Ubuntu",                  # distro WSL avec FreeSurfer\n'
             '    freesurfer_home="/usr/local/freesurfer",\n'
             '    pos_mm=5.0,                           # pas de la grille (mm)\n'
             '    conductivity=(0.3, 0.006, 0.3),       # cerveau, crane, scalp\n'
             '    events="find", event_id={"aud_l": 1},\n'
             '    inverse_method="dSPM", snr=3.0,\n'
             '    loose=1.0,                            # orientation libre (volume)\n'
             ')\n'
             'print(result.source_estimate_file, result.peak)  # ...-vl.stc',
             'from mri2mne.wrapper import reconstruct_sources_volumetric\n\n'
             'result = reconstruct_sources_volumetric(\n'
             '    subject="sampleW",\n'
             '    output_dir="D:/derivatives",\n'
             '    dicom_dir="D:/dicom/sample",          # or t1_path=...\n'
             '    eeg_file="D:/eeg/sample.edf",\n'
             '    digitization="D:/dig/sample.elc",\n'
             '    wsl_distro="Ubuntu",                  # WSL distro with FreeSurfer\n'
             '    freesurfer_home="/usr/local/freesurfer",\n'
             '    pos_mm=5.0,                           # grid spacing (mm)\n'
             '    conductivity=(0.3, 0.006, 0.3),       # brain, skull, scalp\n'
             '    events="find", event_id={"aud_l": 1},\n'
             '    inverse_method="dSPM", snr=3.0,\n'
             '    loose=1.0,                            # free orientation (volume)\n'
             ')\n'
             'print(result.source_estimate_file, result.peak)  # ...-vl.stc')),

            ("h2", _t("Étape 1 — L'anatomie (DICOM → T1)",
                      "Step 1 — Anatomy (DICOM → T1)")),
            ("p", _t(
                "Identique à la route corticale : le DICOM est anonymisé puis "
                "converti en un T1 NIfTI.",
                "Identical to the cortical route: the DICOM is anonymised then "
                "converted to a T1 NIfTI.")),
            ("fig", "t1_ortho.png", _t(
                "Le T1 du sujet, coupes sagittale, coronale et axiale.",
                "The subject's T1, sagittal, coronal and axial slices.")),

            ("h2", _t("Étape 2 — FreeSurfer + BEM à trois couches (WSL)",
                      "Step 2 — FreeSurfer + three-layer BEM (WSL)")),
            ("p", _t(
                "Sous WSL, <code>recon-all -autorecon1</code> puis l'algorithme "
                "<em>watershed</em> extraient trois surfaces frontières — crâne "
                "interne, crâne externe, peau — dont MNE fait un modèle BEM. Le "
                "watershed dépend du sujet : sur un T1 clinique bruité les surfaces "
                "peuvent s'auto-intersecter, d'où l'option <code>bem_strict</code>.",
                "Under WSL, <code>recon-all -autorecon1</code> then the "
                "<em>watershed</em> algorithm extract three boundary surfaces — "
                "inner skull, outer skull, skin — that MNE turns into a BEM model. "
                "Watershed is subject-dependent: on a noisy clinical T1 the surfaces "
                "can self-intersect, hence the <code>bem_strict</code> option.")),
            ("fig", "vol_bem.png", _t(
                "Les trois surfaces BEM (crâne interne en rouge, externe et peau en "
                "jaune) sur des coupes coronales du T1.",
                "The three BEM surfaces (inner skull in red, outer skull and skin "
                "in yellow) over coronal T1 slices.")),

            ("h2", _t("Étape 3 — L'espace de sources volumique",
                      "Step 3 — The volumetric source space")),
            ("p", _t(
                "Au lieu de points sur le cortex, une grille régulière remplit le "
                "volume délimité par le crâne interne. Le pas est réglé par "
                "<code>pos_mm</code> (5 mm ici).",
                "Instead of points on the cortex, a regular grid fills the volume "
                "bounded by the inner skull. The spacing is set by "
                "<code>pos_mm</code> (5 mm here).")),
            ("fig", "vol_source_space.png", _t(
                "Grille de sources (magenta) remplissant le volume cérébral.",
                "Source grid (magenta) filling the brain volume.")),

            ("h2", _t("Étape 4 — La coregistration",
                      "Step 4 — Coregistration")),
            ("p", _t(
                "Même principe que la route corticale, mais dans le repère IRM de "
                "FreeSurfer : les électrodes sont alignées sur la surface de peau "
                "issue du watershed.",
                "Same principle as the cortical route, but in FreeSurfer's MRI "
                "frame: the electrodes are aligned to the watershed skin surface.")),
            ("fig", "vol_coreg.png", _t(
                "Électrodes (rouge) posées sur la peau FreeSurfer après "
                "coregistration.",
                "Electrodes (red) on the FreeSurfer skin surface after "
                "coregistration.")),

            ("h2", _t("Étape 5 — Forward BEM, inverse et sources",
                      "Step 5 — BEM forward, inverse and sources")),
            ("p", _t(
                "Le BEM à trois couches donne le modèle direct sur la grille "
                "volumique ; l'inverse est en orientation libre "
                "(<code>loose=1.0</code>, adapté à un volume). L'estimation est "
                "sauvée en <code>-vl.stc</code> et se visualise sur le T1.",
                "The three-layer BEM gives the forward model on the volume grid; "
                "the inverse uses free orientation (<code>loose=1.0</code>, suited "
                "to a volume). The estimate is saved as <code>-vl.stc</code> and "
                "is visualised on the T1.")),
            ("fig", "vol_sources.png", _t(
                "Estimation dSPM volumique au pic, superposée au T1 (vue "
                "orthogonale, croix sur le maximum).",
                "Volumetric dSPM estimate at the peak, overlaid on the T1 "
                "(orthogonal view, crosshair on the maximum).")),
            ("fig", "vol_timecourse.png", _t(
                "Décours temporel de la source volumique la plus forte.",
                "Time course of the strongest volume source.")),
            ("note", _t(
                "La sortie diffère de la route corticale : un unique fichier "
                "<code>-vl.stc</code> (volume) au lieu de <code>-lh.stc</code> / "
                "<code>-rh.stc</code> (surface). <code>result.peak</code> reste la "
                "position du maximum en millimètres IRM.",
                "The output differs from the cortical route: a single "
                "<code>-vl.stc</code> file (volume) instead of "
                "<code>-lh.stc</code> / <code>-rh.stc</code> (surface). "
                "<code>result.peak</code> is still the location of the maximum in "
                "MRI millimetres.")),
        ],
    },
]


# --------------------------------------------------------------------------- #
#  HTML rendering                                                             #
# --------------------------------------------------------------------------- #

STRINGS = {
    "site": _t("Tutoriels mri2mne", "mri2mne tutorials"),
    "home": _t("Accueil", "Home"),
    "prev": _t("Précédent", "Previous"),
    "next": _t("Suivant", "Next"),
    "onthispage": _t("Sur cette page", "On this page"),
    "footer": _t(
        "Figures générées par le pipeline sur le sujet d'exemple. "
        "Reproductible via <code>docs/tutorials/build_tutorials.py</code>.",
        "Figures generated by the pipeline on the example subject. "
        "Reproducible via <code>docs/tutorials/build_tutorials.py</code>."),
    "index_lead": _t(
        "Des tutoriels pas-à-pas, dans l'esprit de ceux de MNE : chaque étape du "
        "pipeline est montrée avec la figure qu'elle produit, sur un même sujet "
        "d'exemple.",
        "Step-by-step tutorials, in the spirit of MNE's: each pipeline stage is "
        "shown with the figure it produces, on one shared example subject."),
}


def _lang_switch(page_id: str, lang: str) -> str:
    other = "en" if lang == "fr" else "fr"
    fname = _page_filename(page_id, other)
    label = "EN" if lang == "fr" else "FR"
    return f'<a class="lang" href="{fname}">{label}</a>'


def _page_filename(page_id: str, lang: str) -> str:
    return f"{page_id}.html" if lang == "fr" else f"{page_id}.en.html"


def _index_filename(lang: str) -> str:
    return "index.html" if lang == "fr" else "index.en.html"


def render_blocks(blocks, lang, assets_rel="_assets") -> str:
    out = []
    for block in blocks:
        kind = block[0]
        if kind in ("h2", "h3"):
            out.append(f"<{kind}>{block[1][lang]}</{kind}>")
        elif kind == "p":
            out.append(f"<p>{block[1][lang]}</p>")
        elif kind == "note":
            out.append(f'<aside class="note">{block[1][lang]}</aside>')
        elif kind == "code":
            src = block[1]
            if isinstance(src, dict):
                src = src[lang]
            out.append(f'<pre class="code"><code>{highlight(src)}</code></pre>')
        elif kind == "fig":
            name, cap = block[1], block[2][lang]
            out.append(
                f'<figure><img src="{assets_rel}/{name}" alt="{html.escape(cap)}" '
                f'loading="lazy"><figcaption>{cap}</figcaption></figure>')
    return "\n".join(out)


def page_html(page, lang) -> str:
    title = page["title"][lang]
    lead = page["lead"][lang]
    body = render_blocks(page["blocks"], lang)

    ordered = sorted(PAGES, key=lambda p: p["order"])
    idx = ordered.index(page)
    prev_p = ordered[idx - 1] if idx > 0 else None
    next_p = ordered[idx + 1] if idx < len(ordered) - 1 else None
    nav = []
    if prev_p:
        nav.append(f'<a class="pn prev" href="{_page_filename(prev_p["id"], lang)}">'
                   f'← {prev_p["title"][lang]}</a>')
    else:
        nav.append("<span></span>")
    if next_p:
        nav.append(f'<a class="pn next" href="{_page_filename(next_p["id"], lang)}">'
                   f'{next_p["title"][lang]} →</a>')
    nav_html = f'<nav class="pager">{"".join(nav)}</nav>'

    toc = "".join(
        f'<li><a href="#{_slug(b[1][lang])}">{b[1][lang]}</a></li>'
        for b in page["blocks"] if b[0] == "h2")

    body = _anchor_headings(body)

    return _document(
        lang=lang, page_id=page["id"], doc_title=title,
        content=f"""
<article>
  <p class="lead">{lead}</p>
  {body}
  {nav_html}
</article>
<aside class="toc">
  <div class="toc-title">{STRINGS['onthispage'][lang]}</div>
  <ul>{toc}</ul>
</aside>""")


def _slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.U).strip().lower()
    return re.sub(r"[\s]+", "-", text)


def _anchor_headings(body: str) -> str:
    def repl(m):
        inner = m.group(1)
        return f'<h2 id="{_slug(inner)}">{inner}</h2>'
    return re.sub(r"<h2>(.*?)</h2>", repl, body)


def index_html(lang) -> str:
    ordered = sorted(PAGES, key=lambda p: p["order"])
    cards = []
    for p in ordered:
        cards.append(
            f'<a class="card" href="{_page_filename(p["id"], lang)}">'
            f'<span class="num">{p["order"]:02d}</span>'
            f'<span class="ct"><strong>{p["title"][lang]}</strong>'
            f'<span>{p["lead"][lang]}</span></span></a>')
    content = f"""
<article>
  <p class="lead">{STRINGS['index_lead'][lang]}</p>
  <div class="cards">{''.join(cards)}</div>
</article>"""
    return _document(lang=lang, page_id="index", doc_title=STRINGS["site"][lang],
                     content=content, is_index=True)


def _document(lang, page_id, doc_title, content, is_index=False) -> str:
    if is_index:
        switch = (f'<a class="lang" href="{_index_filename("en" if lang=="fr" else "fr")}">'
                  f'{"EN" if lang == "fr" else "FR"}</a>')
        home_href = None
    else:
        switch = _lang_switch(page_id, lang)
        home_href = _index_filename(lang)
    home_link = (f'<a class="home" href="{home_href}">{STRINGS["home"][lang]}</a>'
                 if home_href else "")
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(re.sub('<[^>]+>', '', doc_title))} — mri2mne</title>
<link rel="stylesheet" href="tutorials.css">
</head>
<body>
<header class="topbar">
  <a class="brand" href="{_index_filename(lang)}">mri2mne</a>
  <div class="spacer"></div>
  {home_link}
  {switch}
</header>
<main>
  <h1>{doc_title}</h1>
  {content}
</main>
<footer>{STRINGS['footer'][lang]}</footer>
</body>
</html>"""


CSS = """
:root{
  --fg:#1a1f27; --muted:#5b6675; --bg:#ffffff; --soft:#f5f7fa;
  --line:#e3e8ef; --accent:#2b6cb0; --accent-soft:#e8f1fb;
  --code-bg:#f6f8fa; --kw:#a626a4; --st:#50a14f; --cm:#a0a1a7; --nu:#986801;
  --note-bg:#fff8e6; --note-line:#e6b800;
  --maxw:1180px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
  Helvetica,Arial,sans-serif;color:var(--fg);background:var(--bg);
  line-height:1.65;font-size:16px}
.topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;
  gap:14px;padding:10px 20px;background:rgba(255,255,255,.9);
  backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
.topbar .brand{font-weight:700;color:var(--accent);text-decoration:none;
  font-size:18px;letter-spacing:.2px}
.topbar .spacer{flex:1}
.topbar a.home,.topbar a.lang{color:var(--muted);text-decoration:none;
  font-size:14px;padding:4px 10px;border:1px solid var(--line);border-radius:6px}
.topbar a.lang{font-weight:600;color:var(--accent)}
.topbar a:hover{background:var(--soft)}
main{max-width:var(--maxw);margin:0 auto;padding:28px 20px 10px;
  display:grid;grid-template-columns:1fr;gap:0}
h1{font-size:2rem;line-height:1.2;margin:.2em 0 .1em}
main{display:block}
main>h1{max-width:760px;margin-left:auto;margin-right:auto}
article{max-width:760px;margin:0 auto}
.lead{font-size:1.15rem;color:var(--muted);margin:.4em 0 1.6em}
h2{font-size:1.4rem;margin:2em 0 .5em;padding-top:.3em;border-top:1px solid var(--line)}
h3{font-size:1.12rem;margin:1.6em 0 .4em}
p{margin:.7em 0}
a{color:var(--accent)}
code{font-family:"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.9em;background:var(--code-bg);padding:.1em .35em;border-radius:4px}
pre.code{background:var(--code-bg);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;overflow-x:auto;margin:1.1em 0;font-size:.86rem;line-height:1.55}
pre.code code{background:none;padding:0;font-size:inherit}
pre .kw{color:var(--kw)} pre .st{color:var(--st)} pre .cm{color:var(--cm);font-style:italic}
pre .nu{color:var(--nu)} pre .nm{color:var(--fg)}
figure{margin:1.4em 0;text-align:center}
figure img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:10px;
  box-shadow:0 2px 10px rgba(20,30,50,.06);background:#fff}
figcaption{color:var(--muted);font-size:.9rem;font-style:italic;margin-top:.6em;
  max-width:640px;margin-left:auto;margin-right:auto}
aside.note{background:var(--note-bg);border-left:4px solid var(--note-line);
  padding:12px 16px;border-radius:0 8px 8px 0;margin:1.3em 0;font-size:.96rem}
aside.note code{background:rgba(0,0,0,.04)}
.pager{display:flex;justify-content:space-between;gap:16px;margin:2.6em 0 1em;
  padding-top:1.2em;border-top:1px solid var(--line)}
.pager .pn{text-decoration:none;color:var(--accent);font-weight:600;
  padding:10px 14px;border:1px solid var(--line);border-radius:8px;max-width:48%}
.pager .pn:hover{background:var(--accent-soft)}
.pager .next{margin-left:auto;text-align:right}
.toc{display:none}
.cards{display:flex;flex-direction:column;gap:14px;margin:1.4em 0}
.card{display:flex;gap:16px;align-items:flex-start;text-decoration:none;color:inherit;
  border:1px solid var(--line);border-radius:12px;padding:18px 20px;transition:.15s}
.card:hover{border-color:var(--accent);background:var(--accent-soft);
  transform:translateY(-1px)}
.card .num{font-size:1.5rem;font-weight:800;color:var(--accent);opacity:.5;
  font-variant-numeric:tabular-nums}
.card .ct{display:flex;flex-direction:column;gap:4px}
.card .ct strong{font-size:1.1rem}
.card .ct span{color:var(--muted);font-size:.95rem}
footer{max-width:760px;margin:2em auto;padding:1.4em 20px 3em;color:var(--muted);
  font-size:.85rem;border-top:1px solid var(--line)}
@media(min-width:1080px){
  main{max-width:var(--maxw)}
  article{margin:0 0 0 40px;max-width:720px;display:inline-block;vertical-align:top}
  main>h1{max-width:var(--maxw);margin-left:0;padding-left:40px}
}
"""


def build_site(out: Path) -> None:
    (out / "tutorials.css").write_text(CSS, encoding="utf-8")
    for lang in ("fr", "en"):
        (out / _index_filename(lang)).write_text(index_html(lang), encoding="utf-8")
        for page in PAGES:
            (out / _page_filename(page["id"], lang)).write_text(
                page_html(page, lang), encoding="utf-8")
    print(f"  wrote {2 + 2 * len(PAGES)} HTML pages + tutorials.css")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    default_sample = (here.parents[1] / "examples" / "_full_run" / "sample")
    ap.add_argument("--sample-dir", type=Path, default=default_sample,
                    help="The computed example subject (…/_full_run/sample).")
    ap.add_argument("--raw-edf", type=Path, default=None,
                    help="Continuous EEG to show (defaults to sample/eeg/sample_eeg.edf).")
    ap.add_argument("--vol-sample-dir", type=Path, default=None,
                    help="Computed volumetric run (…/_full_run/sampleW). "
                         "Defaults next to --sample-dir.")
    ap.add_argument("--vol-subjects-dir", type=Path, default=None,
                    help="FreeSurfer subjects_dir for the volumetric run "
                         "(defaults to <sample_dir>/../subjects).")
    ap.add_argument("--out", type=Path, default=here,
                    help="Output folder for the HTML site (default: this folder).")
    ap.add_argument("--skip-figures", action="store_true",
                    help="Rebuild only the HTML, reuse existing _assets figures.")
    args = ap.parse_args()

    assets = args.out / "_assets"
    raw_edf = args.raw_edf or (args.sample_dir / "eeg" / "sample_eeg.edf")
    vol_dir = args.vol_sample_dir or (args.sample_dir.parent / "sampleW")
    vol_subjects = args.vol_subjects_dir or (args.sample_dir.parent / "subjects")

    if not args.skip_figures:
        if not args.sample_dir.is_dir():
            ap.error(f"sample dir not found: {args.sample_dir}")
        print("Generating surface figures…")
        generate_figures(args.sample_dir, raw_edf, assets)
        if vol_dir.is_dir():
            print("Generating volumetric figures…")
            generate_volumetric_figures(vol_dir, vol_subjects, assets)
        else:
            print(f"  (skipping volumetric figures: {vol_dir} not found)")
    print("Writing HTML…")
    build_site(args.out)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
