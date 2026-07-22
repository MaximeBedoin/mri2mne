"""Typed configuration loaded from YAML.

Validation happens once, up front, so a typo in config.yaml fails immediately
instead of forty minutes into a `charm` run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import STAGES


class ConfigError(ValueError):
    """Raised when config.yaml is malformed or internally inconsistent."""


@dataclass
class PathsConfig:
    dicom_root: Path
    derivatives_root: Path
    subjects_dir: Path
    digitisation: str  # template containing "{subject}"


@dataclass
class SubjectsConfig:
    include: list[str] | None = None
    exclude: list[str] = field(default_factory=list)


@dataclass
class SimnibsConfig:
    bin_dir: Path | None = None
    t2_template: str | None = None
    extra_args: list[str] = field(default_factory=list)
    timeout_s: int = 21600


@dataclass
class AnonymizeConfig:
    enabled: bool = True
    deface: bool = False


@dataclass
class FemConfig:
    """SimNIBS FEM leadfield / cortical source space settings."""

    subsampling: int | None = 10000   # cortical source points per hemisphere
    cpus: int = 1                     # forced to 1 on Windows (see simnibs_forward)
    morph_to_fsaverage: int | None = 5  # fsaverage subdivision for group analysis


@dataclass
class BemConfig:
    """FreeSurfer BEM / volumetric source space settings (Route C, via WSL)."""

    pos_mm: float = 5.0                # volume source grid spacing
    conductivity: tuple[float, float, float] = (0.3, 0.006, 0.3)
    ico: int | None = 4               # BEM surface tessellation order
    strict: bool = True               # refuse self-intersecting watershed surfaces
    wsl_distro: str | None = None     # None = default WSL distro
    freesurfer_home: str | None = None  # None = auto-detect ($HOME/freesurfer, ...)


@dataclass
class CoregConfig:
    icp_iterations: int = 20
    omit_distance_mm: float = 15.0
    max_residual_mm: float = 5.0


@dataclass
class RunConfig:
    n_jobs: int | None = None
    force: list[str] = field(default_factory=list)
    continue_on_error: bool = True
    cleanup_intermediates: bool = True


@dataclass
class Config:
    paths: PathsConfig
    subjects: SubjectsConfig
    simnibs: SimnibsConfig
    anonymize: AnonymizeConfig
    fem: FemConfig
    coregistration: CoregConfig
    run: RunConfig
    head_model: str = "fem"           # "fem" (SimNIBS, Windows) or "bem" (FreeSurfer/WSL)
    bem: BemConfig = field(default_factory=BemConfig)

    def resolved_n_jobs(self) -> int:
        """Parallel workers, defaulting to a quarter of the cores.

        `charm` peaks around 4-8 GB and is itself partly threaded, so saturating
        the core count trades throughput for swapping.
        """
        if self.run.n_jobs is not None:
            return max(1, int(self.run.n_jobs))
        return max(1, (os.cpu_count() or 4) // 4)

    def threads_per_worker(self) -> int:
        """Cores to hand each parallel subject.

        Without this, charm either takes the whole machine per subject (workers
        then fight) or gets pinned to one thread (most of the machine idles
        through the pipeline's longest step).
        """
        return max(1, (os.cpu_count() or 4) // self.resolved_n_jobs())

    def digitisation_for(self, subject: str) -> Path:
        return Path(self.paths.digitisation.format(subject=subject))

    def t2_for(self, subject: str) -> Path | None:
        if not self.simnibs.t2_template:
            return None
        return Path(self.simnibs.t2_template.format(subject=subject))


def _require(section: dict[str, Any], key: str, where: str) -> Any:
    if key not in section or section[key] is None:
        raise ConfigError(f"Missing required key '{key}' in section '{where}'.")
    return section[key]


def load_config(path: str | Path) -> Config:
    """Parse and validate config.yaml."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    paths_raw = raw.get("paths") or {}
    paths = PathsConfig(
        dicom_root=Path(_require(paths_raw, "dicom_root", "paths")),
        derivatives_root=Path(_require(paths_raw, "derivatives_root", "paths")),
        subjects_dir=Path(_require(paths_raw, "subjects_dir", "paths")),
        digitisation=str(_require(paths_raw, "digitisation", "paths")),
    )
    if "{subject}" not in paths.digitisation:
        raise ConfigError(
            "paths.digitisation must contain the '{subject}' placeholder so it "
            "can resolve to a different file per subject."
        )

    subjects_raw = raw.get("subjects") or {}
    subjects = SubjectsConfig(
        include=subjects_raw.get("include"),
        exclude=list(subjects_raw.get("exclude") or []),
    )

    simnibs_raw = raw.get("simnibs") or {}
    bin_dir = simnibs_raw.get("bin_dir")
    simnibs = SimnibsConfig(
        bin_dir=Path(bin_dir) if bin_dir else None,
        t2_template=simnibs_raw.get("t2_template"),
        extra_args=list(simnibs_raw.get("extra_args") or []),
        timeout_s=int(simnibs_raw.get("timeout_s", 21600)),
    )

    anon_raw = raw.get("anonymize") or {}
    anonymize = AnonymizeConfig(
        enabled=bool(anon_raw.get("enabled", True)),
        deface=bool(anon_raw.get("deface", False)),
    )

    fem_raw = raw.get("fem") or {}
    sub = fem_raw.get("subsampling", 10000)
    fem = FemConfig(
        subsampling=None if sub is None else int(sub),
        cpus=int(fem_raw.get("cpus", 1)),
        morph_to_fsaverage=(
            None if fem_raw.get("morph_to_fsaverage", 5) is None
            else int(fem_raw.get("morph_to_fsaverage", 5))
        ),
    )

    coreg_raw = raw.get("coregistration") or {}
    coregistration = CoregConfig(
        icp_iterations=int(coreg_raw.get("icp_iterations", 20)),
        omit_distance_mm=float(coreg_raw.get("omit_distance_mm", 15.0)),
        max_residual_mm=float(coreg_raw.get("max_residual_mm", 5.0)),
    )

    run_raw = raw.get("run") or {}
    force = list(run_raw.get("force") or [])
    unknown = set(force) - set(STAGES)
    if unknown:
        raise ConfigError(
            f"run.force contains unknown stage(s): {sorted(unknown)}. "
            f"Valid stages: {list(STAGES)}"
        )
    run = RunConfig(
        n_jobs=run_raw.get("n_jobs"),
        force=force,
        continue_on_error=bool(run_raw.get("continue_on_error", True)),
        cleanup_intermediates=bool(run_raw.get("cleanup_intermediates", True)),
    )

    head_model = str(raw.get("head_model", "fem")).lower()
    if head_model not in ("fem", "bem"):
        raise ConfigError(
            f"head_model must be 'fem' (SimNIBS, Windows-native) or 'bem' "
            f"(FreeSurfer via WSL), got {head_model!r}."
        )

    bem_raw = raw.get("bem") or {}
    cond = bem_raw.get("conductivity") or [0.3, 0.006, 0.3]
    if len(cond) != 3:
        raise ConfigError("bem.conductivity must be 3 values (brain, skull, scalp).")
    bem = BemConfig(
        pos_mm=float(bem_raw.get("pos_mm", 5.0)),
        conductivity=tuple(float(c) for c in cond),
        ico=None if bem_raw.get("ico", 4) is None else int(bem_raw.get("ico", 4)),
        strict=bool(bem_raw.get("strict", True)),
        wsl_distro=bem_raw.get("wsl_distro"),
        freesurfer_home=bem_raw.get("freesurfer_home"),
    )

    return Config(
        paths=paths,
        subjects=subjects,
        simnibs=simnibs,
        anonymize=anonymize,
        fem=fem,
        coregistration=coregistration,
        run=run,
        head_model=head_model,
        bem=bem,
    )
