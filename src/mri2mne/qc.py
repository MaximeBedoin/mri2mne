"""Per-subject QC report.

A silently wrong coregistration produces numbers that look entirely normal
downstream, so every subject gets an HTML report with the figures needed to
catch that by eye.

QC is best-effort: a failure to render a figure must never invalidate a
forward solution that computed correctly, so each section is guarded.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

# Batch runs have no display and the workers are not the main thread.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .paths import SubjectPaths  # noqa: E402


def _add_alignment_section(
    report, paths: SubjectPaths, info, logger: logging.Logger
) -> None:
    """3D sensor/scalp alignment -- the key anatomy QC for the FEM route.

    Needs an offscreen GL context, the most fragile part of QC on a headless
    Windows box, so a failure here degrades the report rather than invalidating
    it.
    """
    try:
        import mne

        mne.viz.set_3d_backend("pyvistaqt", verbose="ERROR")
    except Exception as exc:  # noqa: BLE001
        logger.warning("No usable 3D backend; skipping alignment figure: %s", exc)
        return

    try:
        report.add_trans(
            trans=str(paths.trans),
            info=info,
            subject=paths.subject,
            subjects_dir=str(paths.subjects_dir),
            alpha=0.7,
            title="Sensor / scalp alignment",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not render 3D alignment figure: %s", exc)


def _residual_figure(distances_mm: np.ndarray, max_residual_mm: float):
    """Histogram of digitised-point to scalp distances."""
    fig, ax = plt.subplots(figsize=(6, 3.2), constrained_layout=True)
    ax.hist(distances_mm, bins=30, color="#4477aa", edgecolor="white")
    median = float(np.median(distances_mm))
    ax.axvline(median, color="#cc3311", lw=2, label=f"median {median:.2f} mm")
    ax.axvline(
        max_residual_mm, color="#ee7733", lw=2, ls="--",
        label=f"threshold {max_residual_mm:.1f} mm",
    )
    ax.set_xlabel("Distance from digitised point to scalp (mm)")
    ax.set_ylabel("Count")
    ax.set_title("Coregistration residual")
    ax.legend()
    return fig


def _metrics_html(metrics: dict[str, float], flags: list[str]) -> str:
    rows = "".join(
        f"<tr><td style='padding:4px 12px'>{k}</td>"
        f"<td style='padding:4px 12px;text-align:right'>{v:.3f}</td></tr>"
        for k, v in sorted(metrics.items())
        if isinstance(v, (int, float))
    )
    flag_html = ""
    if flags:
        items = "".join(f"<li>{f}</li>" for f in flags)
        flag_html = (
            "<p style='color:#cc3311'><strong>Needs review:</strong></p>"
            f"<ul style='color:#cc3311'>{items}</ul>"
        )
    return f"{flag_html}<table style='border-collapse:collapse'>{rows}</table>"


def build_report(
    paths: SubjectPaths,
    info,
    metrics: dict[str, float],
    flags: list[str],
    max_residual_mm: float,
    logger: logging.Logger,
    coreg_distances_mm: np.ndarray | None = None,
) -> Path | None:
    """Render the subject's HTML QC report. Returns None if reporting failed."""
    try:
        import mne

        report = mne.Report(title=f"mri2mne - {paths.subject}", verbose="ERROR")

        report.add_html(
            _metrics_html(metrics, flags), title="Metrics", section="Summary"
        )

        if coreg_distances_mm is not None and coreg_distances_mm.size:
            fig = _residual_figure(coreg_distances_mm, max_residual_mm)
            report.add_figure(fig, title="Coregistration residual", section="Coregistration")
            plt.close(fig)

        _add_alignment_section(report, paths, info, logger)

        paths.qc_dir.mkdir(parents=True, exist_ok=True)
        report.save(str(paths.report), overwrite=True, open_browser=False, verbose="ERROR")
        logger.info("Wrote QC report -> %s", paths.report)
        return paths.report
    except Exception as exc:  # noqa: BLE001 - QC must never fail the subject
        logger.warning("QC report generation failed: %s", exc)
        return None


def write_batch_summary(results: list[dict], out_path: Path) -> Path:
    """Aggregate the per-subject outcomes into one HTML table."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def cell(value) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        return "" if value is None else str(value)

    header = [
        "subject", "status", "coreg_residual_median_mm", "fwd_n_sources",
        "fwd_n_channels", "flags", "error",
    ]
    rows = []
    for res in sorted(results, key=lambda r: str(r.get("subject"))):
        status = res.get("status", "?")
        colour = {
            "ok": "#e8f5e9", "flagged": "#fff8e1", "failed": "#ffebee"
        }.get(status, "#ffffff")
        cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{cell(res.get(h))}</td>"
            for h in header
        )
        rows.append(f"<tr style='background:{colour}'>{cells}</tr>")

    head_html = "".join(
        f"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left'>{h}</th>"
        for h in header
    )
    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_flag = sum(1 for r in results if r.get("status") == "flagged")
    n_fail = sum(1 for r in results if r.get("status") == "failed")

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>mri2mne batch summary</title></head>
<body style="font-family:system-ui,sans-serif;margin:2rem">
<h1>mri2mne batch summary</h1>
<p>{n_ok} ok &middot; {n_flag} flagged for review &middot; {n_fail} failed
   &middot; {len(results)} total</p>
<table style="border-collapse:collapse">
<thead><tr>{head_html}</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
