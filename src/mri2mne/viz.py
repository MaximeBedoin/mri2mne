"""Interactive and offscreen visualisation of the cortical source estimate.

MNE's surface plotting (`stc.plot`, `mne.viz.Brain`, movies) expects a
FreeSurfer `subjects_dir/<subject>/surf/lh.white` layout. Our cortical source
space is a SimNIBS *central* surface, not a FreeSurfer subject, so those files
do not exist on disk. Because the source space keeps its full triangulation and
uses every vertex (`nuse == np`), the stc vertex numbering already matches the
mesh -- so we simply write that SimNIBS mesh once in FreeSurfer surface format
and MNE then treats the subject as a native FreeSurfer subject. The whole
`mne.viz.Brain` toolbox (rotate-with-the-mouse window, time slider, movies,
ROI time courses) works unchanged afterwards.

Typical use, from an external script on the analyst's own machine::

    from mri2mne.viz import open_viewer
    brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
    # ... an interactive window opens; block until it is closed:
    from mri2mne.viz import block_on_viewer
    block_on_viewer()

For a headless report figure instead of a window, use ``save_views`` (it renders
offscreen and writes a PNG).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .paths import SubjectPaths

# The three surface names stc.plot may ask for. SimNIBS gives us one real
# (folded) cortical surface; we write it under every name so any `surface=`
# choice resolves. There is no true inflated geometry (SimNIBS does not inflate),
# so surface="inflated" looks identical to "white" -- for a genuinely inflated,
# smooth brain, morph to fsaverage (pipeline option `morph_to_fsaverage`) and
# plot with subject="fsaverage".
_SURF_NAMES = ("white", "pial", "inflated")


class VizError(RuntimeError):
    """Raised when the source estimate cannot be turned into a brain plot."""


def _log(logger: logging.Logger | None, level: int, msg: str, *args) -> None:
    if logger is not None:
        logger.log(level, msg, *args)


def write_freesurfer_surfaces(
    paths: SubjectPaths,
    *,
    source_space: str | Path | None = None,
    overwrite: bool = False,
    logger: logging.Logger | None = None,
) -> Path:
    """Write the SimNIBS cortical mesh as FreeSurfer surfaces for MNE.

    Reads the two-hemisphere surface source space (``paths.source_space`` unless
    ``source_space`` is given) and writes ``lh/rh.{white,pial,inflated}`` plus a
    flat ``lh/rh.curv`` into ``paths.surf_dir``. Idempotent: skips writing when
    the files already exist unless ``overwrite`` is set.

    Returns the ``subjects_dir`` to hand to MNE's ``subject=paths.subject``.
    """
    import mne

    src_path = Path(source_space) if source_space else paths.source_space
    if not src_path.is_file():
        raise VizError(
            f"Source space not found: {src_path}. Run the forward stage first."
        )

    surf_dir = paths.surf_dir
    expected = [surf_dir / f"{h}.{n}" for h in ("lh", "rh") for n in _SURF_NAMES]
    if not overwrite and all(p.exists() for p in expected):
        _log(logger, logging.INFO, "FreeSurfer surfaces already present in %s", surf_dir)
        return paths.subjects_dir

    src = mne.read_source_spaces(str(src_path), verbose="ERROR")
    if len(src) != 2 or any(s.get("type") != "surf" for s in src):
        raise VizError(
            "Expected a two-hemisphere cortical (surface) source space; got "
            f"{len(src)} space(s) of type "
            f"{[s.get('type') for s in src]}. Volumetric estimates cannot be "
            "plotted on a cortical surface."
        )

    surf_dir.mkdir(parents=True, exist_ok=True)
    for hemi, s in zip(("lh", "rh"), src):
        # Write the FULL mesh: tris index into all np points, and the stc's
        # vertex numbers (vertno) index into that same array, so the data lands
        # on the right vertices even if the space were ever decimated (np>nuse).
        rr_mm = np.asarray(s["rr"], dtype=np.float64) * 1000.0  # m -> mm
        tris = np.asarray(s["tris"], dtype=np.int32)
        for name in _SURF_NAMES:
            mne.write_surface(
                str(surf_dir / f"{hemi}.{name}"), rr_mm, tris, overwrite=True
            )
        _write_flat_curv(surf_dir / f"{hemi}.curv", len(rr_mm), logger)

    _log(logger, logging.INFO, "Wrote SimNIBS surfaces (FreeSurfer format) -> %s",
         surf_dir)
    return paths.subjects_dir


def _write_flat_curv(path: Path, n_vertices: int, logger: logging.Logger | None) -> None:
    """Write a zero curvature map so the plotter has a uniform background.

    Optional: if the writer is unavailable, MNE falls back to a flat cortex on
    its own, so a failure here must not break plotting.
    """
    try:
        import nibabel.freesurfer.io as fsio

        fsio.write_morph_data(str(path), np.zeros(n_vertices, dtype=np.float32))
    except Exception as exc:  # noqa: BLE001 - purely cosmetic background shading
        _log(logger, logging.WARNING, "Could not write %s (%s); using flat cortex",
             path.name, exc)


def plot_sources(
    paths: SubjectPaths,
    *,
    initial_time: float | None = None,
    hemi: str = "both",
    surface: str = "white",
    colormap: str = "hot",
    clim="auto",
    time_viewer: bool = True,
    show_traces="auto",
    source_estimate: str | Path | None = None,
    overwrite_surfaces: bool = False,
    logger: logging.Logger | None = None,
    **plot_kwargs,
):
    """Open MNE's surface brain plot for this subject's source estimate.

    With ``time_viewer=True`` (the default) this opens the interactive
    rotate-with-the-mouse window with a time slider -- run it from a normal
    Python session or a script (see ``block_on_viewer``). With
    ``time_viewer=False`` it returns a non-interactive ``Brain`` suitable for
    offscreen screenshots.

    Extra keyword arguments pass straight through to ``stc.plot``.

    Returns the ``mne.viz.Brain``.
    """
    import mne

    write_freesurfer_surfaces(paths, overwrite=overwrite_surfaces, logger=logger)

    stc_stem = Path(source_estimate) if source_estimate else paths.source_estimate
    try:
        stc = mne.read_source_estimate(str(stc_stem), subject=paths.subject)
    except Exception as exc:  # noqa: BLE001 - surface many reader errors as one
        raise VizError(
            f"Could not read the source estimate at {stc_stem}(-lh/-rh.stc): {exc}"
        ) from exc

    if clim == "auto":
        clim = dict(kind="percent", lims=[90, 97, 99.9])

    return stc.plot(
        subject=paths.subject,
        subjects_dir=str(paths.subjects_dir),
        surface=surface,
        hemi=hemi,
        initial_time=initial_time,
        clim=clim,
        colormap=colormap,
        time_viewer=time_viewer,
        show_traces=show_traces,
        **plot_kwargs,
    )


def open_viewer(
    output_dir: str | Path,
    subject: str,
    *,
    subjects_dir: str | Path | None = None,
    **kwargs,
):
    """Convenience: build the standard paths and open the interactive viewer.

    Mirrors how the wrapper lays out a subject, so it addresses the output of a
    normal ``reconstruct_sources`` / batch run by ``output_dir`` and ``subject``
    alone.
    """
    output_dir = Path(output_dir)
    paths = SubjectPaths(
        subject=subject,
        derivatives_root=output_dir,
        subjects_dir=Path(subjects_dir) if subjects_dir else output_dir / "subjects",
    )
    return plot_sources(paths, **kwargs)


def block_on_viewer() -> None:
    """Enter the Qt event loop so an interactive window stays open in a script.

    In an interactive session (IPython with the qt GUI, Jupyter) the window
    already stays live and this is a no-op. In a plain ``python script.py`` the
    interpreter would otherwise exit and close the window immediately; calling
    this at the end blocks until the user closes the window.
    """
    try:
        from qtpy.QtWidgets import QApplication
    except Exception:  # noqa: BLE001 - no Qt: nothing to block on
        return
    app = QApplication.instance()
    if app is not None:
        app.exec()


def save_views(
    paths: SubjectPaths,
    out_png: str | Path,
    *,
    initial_time: float | None = None,
    views=("lateral", "medial", "dorsal"),
    hemi: str = "lh",
    surface: str = "white",
    colormap: str = "hot",
    clim="auto",
    logger: logging.Logger | None = None,
) -> Path:
    """Render a static multi-view PNG offscreen (for reports / headless boxes).

    Does not need a display: forces PyVista offscreen, so it is safe inside the
    batch QC step. Returns the written path.
    """
    import os

    os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    brain = plot_sources(
        paths, initial_time=initial_time, hemi=hemi, surface=surface,
        colormap=colormap, clim=clim, time_viewer=False, show_traces=False,
        time_label=None, background="white", size=(700, 650), logger=logger,
    )

    shots = []
    for view in views:
        brain.show_view(view)
        shots.append(np.asarray(brain.screenshot()))
    brain.close()

    fig, axes = plt.subplots(1, len(shots), figsize=(5 * len(shots), 5))
    if len(shots) == 1:
        axes = [axes]
    for ax, shot, view in zip(axes, shots, views):
        ax.imshow(shot)
        ax.set_title(view, fontsize=11)
        ax.axis("off")
    if initial_time is not None:
        fig.suptitle(f"dSPM sources at t = {initial_time * 1000:.0f} ms", fontsize=13)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_png), dpi=130, bbox_inches="tight")
    plt.close(fig)
    _log(logger, logging.INFO, "Wrote source-estimate views -> %s", out_png)
    return out_png
