> 🌍 [Français](README.md) · **English** · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · [العربية](README.ar.md)

# MRI → MNE: cortical EEG source analysis (SimNIBS FEM, Windows-native)

Complete pipeline from an **MRI in DICOM** + an **EEG recording** to a
**cortical source estimate** with MNE-Python. Driven in Python, runs natively on
Windows, **without FreeSurfer, without WSL, without Docker**. (An optional
volumetric BEM route is described further down; that one does use WSL +
FreeSurfer.)

The method is built entirely on **established, citable** libraries: segmentation
and **FEM** forward by **SimNIBS** (`charm`, `compute_tdcs_leadfield`,
`make_forward`), coregistration and inverse by **MNE-Python**. This repository's
code is only the orchestration between the two.

Budget **~1.5 h per subject** for `charm` + **~20-40 min** for the FEM leadfield,
instead of the 10-20 h of `recon-all`.

> 📚 **Illustrated tutorials** — step by step, with the figure for **each stage**
> (T1, tissue segmentation, EEG, evoked response, 3D coregistration, cortical
> sources): **[maximebedoin.github.io/mri2mne/tutorials](https://maximebedoin.github.io/mri2mne/tutorials/index.en.html)**
> (once **GitHub Pages** is enabled). Otherwise, open `docs/tutorials/index.en.html` locally.

---

## Input → output, in one sentence

**You start from** the patient's anatomical MRI in DICOM + the EEG recording (EDF
or other) + the electrode digitization. **You arrive at** the EEG source estimate
on the **cortex**: the localization of the measured activity, plus a morph to
`fsaverage` for group analysis.

## What the pipeline produces

For each subject, in `derivatives/<subject>/mne/`:

| File | Content |
|---|---|
| `<subject>-trans.fif` | Head ↔ MRI coregistration |
| `<subject>-fwd.fif` | **FEM** forward on the **cortical** source space (lh+rh) |
| `<subject>-noise-cov.fif` | Noise covariance |
| `<subject>-inv.fif` | Inverse operator |
| `<subject>-lh.stc` / `-rh.stc` | **Cortical source estimate** — the deliverable |
| `<subject>-morph.h5` | Morph to `fsaverage` (group analysis) |

Two levels of use:

* **`reconstruct_sources()`** (one subject, see below) goes from MRI+EEG all the
  way to the source estimate.
* **`run_pipeline.py`** (batch) chains conversion → `charm` → coreg → FEM forward
  for N subjects; the inverse (which depends on the EEG data) is then done via the
  wrapper.

---

## End-to-end example (`data/` folder)

The repository ships a ready-to-use example in [`data/`](data/README.en.md): one
patient with MRI DICOM + EEG + digitization (plus a second one for the batch).

```
data/
  patient01/
    dicom/                 # T1w MRI series (DICOM)
    patient01_eeg.edf      # EEG
    patient01_dig.fif      # electrode digitization
    patient01-eve.fif      # events
  patient02/               # same (for the batch)
  config.batch.yaml        # ready-to-use batch config
  README.md                # structure and provenance details
```

**File provenance** (details in [data/README.md](data/README.en.md)):

| File | Origin | Nature |
|---|---|---|
| `dicom/` | Public `datalad/example-dicom-structural` dataset (`PatientIdentityRemoved=YES`) | Real T1w MRI, **anonymized** |
| `*_eeg.edf`, `*_dig.fif`, `*-eve.fif` | **MNE-Python** `sample` dataset | EEG + digitization of a **different** subject |
| `patient02/` | Copy of `patient01` | Only to demonstrate the batch |

> ⚠️ The EEG and the MRI come from **different subjects**: they are **stand-ins**
> to illustrate the folder structure and the commands. The chain runs end to end,
> but **the result has no clinical meaning**. For a real subject, the EEG and the
> digitization must come from the **same** patient as the MRI.

### Single run — one patient, outputs stored under the patient

Surface (FEM, Windows-native):

```python
from mri2mne.wrapper import reconstruct_sources

reconstruct_sources(
    subject="patient01",
    output_dir="data/patient01/surface",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- REPLACE with your path
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/surface/patient01/mne/patient01-lh.stc  (+ -rh.stc)
```

Volumetric (BEM, via WSL + FreeSurfer):

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="data/patient01/volumetric",
    dicom_dir="data/patient01/dicom",
    eeg_file="data/patient01/patient01_eeg.edf",
    digitization="data/patient01/patient01_dig.fif",
    events="data/patient01/patient01-eve.fif", event_id={"aud_l": 1},
)
# -> data/patient01/volumetric/patient01/mne/patient01-vol-vl.stc
```

### Batch — several patients, one command

> **Before running**: edit [`data/config.batch.yaml`](data/config.batch.yaml)
> and replace `simnibs.bin_dir` (placeholder `C:/Users/YOUR_NAME/...`) with the
> `Scripts` folder of your `simnibs_env`. `--check` verifies it and reports a
> clear error if the path is still the placeholder.

```powershell
python run_pipeline.py --config data/config.batch.yaml --check   # checks tools + inputs
python run_pipeline.py --config data/config.batch.yaml
```

The config's `head_model` field (`fem` or `bem`) picks the route; the batch
outputs go under `data/_batch_derivatives/`. The EEG inverse is then done per
subject with the corresponding wrapper.

> The example EEG/digitization come from a **different** subject than the MRI
> (stand-ins for the demo): the chain runs, but the result has no clinical
> meaning. See [data/README.md](data/README.en.md).

---

## Architecture: two environments

The pipeline uses **two conda environments**:

* **`mri2mne`** — drives everything (this repo). **Never** imports `simnibs`.
* **`simnibs_env`** — SimNIBS 4.6 + MNE. Runs the SimNIBS-specific steps, called
  as **subprocesses** by `mri2mne`.

This is what lets us use SimNIBS and MNE in their native versions without a
dependency conflict (numpy in particular).

### The steps, and the library behind each

| # | Step | Function | Library |
|---|---|---|---|
| 1 | DICOM → NIfTI + anonymization + T1 selection | `dcm2niix`, `pydicom` | — |
| 2 | Segmentation + FEM mesh + cortical surfaces | `charm` | SimNIBS |
| 3a | Scalp surface (for the ICP) | `mesh.crop_mesh` | SimNIBS |
| 3b | Subject fiducials | `read_csv_positions` | SimNIBS |
| 3c | Fiducial alignment + ICP | `Coregistration` | MNE |
| 4a | Electrode montage → subject | `prepare_montage` | SimNIBS |
| 4b | FEM leadfield (reciprocity) | `compute_tdcs_leadfield` | SimNIBS |
| 4c | Conversion to `mne.Forward` (+ fsaverage morph) | `make_forward` | SimNIBS |
| 5 | EEG: reading, filtering, covariance | `mne.io`, `compute_covariance` | MNE |
| 6 | Inverse operator + application | `make_inverse_operator`, `apply_inverse` | MNE |

Coordinate frame: the SimNIBS mesh world is treated as MNE's "MRI" frame, which
lets us reuse `Coregistration` without conversion.

---

## Wrapper function: from MRI+EEG to sources, in one call

```python
from mri2mne.wrapper import reconstruct_sources

result = reconstruct_sources(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # or t1_path="..." for a ready T1
    eeg_file="D:/eeg/patient01.edf",         # .edf .bdf .vhdr .set .fif ...
    digitization="D:/dig/patient01.elc",     # electrode positions
    simnibs_bin_dir="C:/Users/me/Miniconda3/envs/simnibs_env/Scripts",  # <- REPLACE with your path
    events="find",                            # detects the triggers; or an array / -eve.fif
    event_id={"spike": 1},
    tmin=-0.2, tmax=0.5,
    inverse_method="dSPM",                    # or MNE / sLORETA / eLORETA
)

print(result.source_estimate_file)   # ...-lh.stc
print(result.peak)                    # peak: time + hemisphere + position (mm)
stc = result.stc                      # cortical SourceEstimate in memory
```

Main arguments (the others have sensible defaults):

| Group | Arguments |
|---|---|
| Anatomy | `dicom_dir` **or** `t1_path`, `t2_path` |
| EEG | `eeg_file`, `digitization` |
| SimNIBS | `simnibs_bin_dir` (Scripts folder of `simnibs_env`) |
| FEM forward | `fem_subsampling` (cortical sources/hemisphere), `fem_cpus`, `morph_to_fsaverage` |
| Coregistration | `icp_iterations`, `omit_distance_mm` |
| EEG processing | `l_freq`, `h_freq`, `eeg_reference`, `events`, `event_id`, `tmin`, `tmax`, `baseline`, `reject`, `noise_cov_tmin/tmax` |
| Inverse | `inverse_method`, `snr` |

`reconstruct_sources()` never raises on a processing error: it returns a
`SourceResult` with `status="failed"` and the message, so it stays safe to call
in a loop. Already-computed stages are skipped (resume by file existence;
`force=[...]` to recompute).

> Alternative: an LCMV beamformer (`mne.beamformer.make_lcmv`) is often used
> clinically; it would be a direct extension of `inverse.py`.

---

## Alternative route: volumetric sources (BEM, WSL2 + FreeSurfer)

In addition to the surface FEM route (default, 100% Windows), the repository
provides a **second, volumetric route**, built on **FreeSurfer's 3-layer BEM** —
the standard BEM method, recognized clinically. The sources fill the brain volume
(3D grid) instead of the cortex, and the output is a `VolSourceEstimate`
(`-vl.stc`) that is read as an **overlay on the MRI** (slices).

The two routes are **independent and complementary** (distinct coordinate frames,
distinct files). Again, every computation is a library call: FreeSurfer
`recon-all -autorecon1` / `mri_watershed`; MNE `make_bem_solution` /
`setup_volume_source_space` / `make_forward_solution` / `make_inverse_operator`.

### Prerequisites: WSL2 + FreeSurfer

Since FreeSurfer is Linux-only, this route runs it inside **WSL2** (the driver
stays on Windows and calls it as a subprocess, like SimNIBS).

```powershell
wsl --install            # WSL2 + Ubuntu, if not already present
```

Then, in the Ubuntu terminal, install FreeSurfer 7.x via its **tarball**
(recommended on Ubuntu 24.04):

```bash
sudo apt install -y tcsh          # required by the FreeSurfer scripts
cd ~ && wget https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
sudo tar -C /usr/local -xzf freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz
# free license: https://surfer.nmr.mgh.harvard.edu/registration.html
cp /mnt/c/path/to/license.txt $FREESURFER_HOME/license.txt
```

Budget ~20 GB for the installation. Check from Python:
`from mri2mne import wsl; print(wsl.check_freesurfer().describe())` should print
"... (licensed)".

### Usage

```python
from mri2mne.wrapper import reconstruct_sources_volumetric

result = reconstruct_sources_volumetric(
    subject="patient01",
    output_dir="D:/derivatives",
    dicom_dir="D:/dicom/patient01",          # or t1_path="..."
    eeg_file="D:/eeg/patient01.edf",
    digitization="D:/dig/patient01.elc",
    events="find", event_id={"spike": 1},
    pos_mm=5.0,                               # volumetric grid spacing
    inverse_method="dSPM", snr=3.0,
)
print(result.source_estimate_file)   # ...-vl.stc
```

Cost: **~20 min/subject** on a clean T1 — not the hours of a full `recon-all`,
which is not needed here.

**In batch**, just set `head_model: "bem"` in `config.yaml` (the `bem:` section
for the settings): `run_pipeline.py` then routes the `headmodel`/`coreg`/`forward`
steps to FreeSurfer/BEM instead of SimNIBS/FEM, while reusing the same cache, the
same `--check` (which verifies WSL + FreeSurfer) and the same QC. The EEG inverse
is then done via `reconstruct_sources_volumetric`.

### Caveat: watershed surface quality

`mri_watershed` is **sensitive to T1 quality**. On a clean research T1 (1 mm) it
produces closed, nested surfaces; on some atypical clinical acquisitions (large
FOV, unusual contrast) the skull can self-intersect. The pipeline **detects and
flags** this case (`volumetric.check_bem_surfaces`) with a clear message instead
of crashing — the subject then needs surface QC or a cleaner T1. For a crisp 3D
cortex in visualization, prefer the **surface route** (that is its purpose).

---

## Installation

### 1. `simnibs_env` — SimNIBS 4 (provides `charm` + the FEM solver)

Command-line method (validated here, no clicking):

```powershell
curl -L -o environment_windows.yml https://github.com/simnibs/simnibs/releases/download/v4.6.0/environment_windows.yml
conda env create -f environment_windows.yml
conda activate simnibs_env
pip install https://github.com/simnibs/simnibs/releases/download/v4.6.0/simnibs-4.6.0-cp311-cp311-win_amd64.whl
pip install "mne>=1.6"     # required for make_forward (MNE output)
```

Check: `charm --version` should print `4.6.0`. The folder
`…\envs\simnibs_env\Scripts` is the one passed to `simnibs_bin_dir`. (The official
graphical installer from <https://simnibs.github.io> works too; you then need to
`pip install mne` into its Python.)

### 2. `mri2mne` — the driving environment

```powershell
conda env create -f environment.yml
conda activate mri2mne
```

### 3. Configuration

```powershell
copy config.example.yaml config.yaml
```

Edit `config.yaml`: data paths, `simnibs.bin_dir` (the `Scripts` folder of
`simnibs_env`), and the `paths.digitisation` template.

### 4. (Optional) Install as a pip package

The repository is an installable package (`pyproject.toml`, `src/` layout). This
is the simplest way to deploy it **without WSL**: the surface FEM route and the
batch depend only on PyPI libraries. From the repository root:

```powershell
pip install .                # installs the package + its dependencies
pip install ".[viz]"         # + PyVista/VTK (3D QC + source viewer)
pip install ".[all]"         # + dcm2niix (binary) + pytest
pip install -e ".[dev]"      # development (editable) mode + pytest
```

After installation:

```python
from mri2mne.wrapper import reconstruct_sources   # importable anywhere
```

and the batch command is available directly (no more need for
`run_pipeline.py`):

```powershell
mri2mne --config config.yaml --check
mri2mne --config config.yaml
```

What the pip install **does not** cover, by design:

* **SimNIBS** (`charm` + FEM solver) stays in its own `simnibs_env`, called as a
  subprocess (see §1) — never installed in the same env as the driver (numpy
  conflict).
* The **volumetric BEM route** requires **FreeSurfer in WSL2** (a system
  prerequisite, see above); it adds no Python dependency. The surface route, on
  the other hand, installs and runs **entirely without WSL**.

> `pip install .` remains possible even without SimNIBS or WSL: the library
> imports and the tests pass; only the steps that actually call `charm`/FreeSurfer
> require those tools at runtime.

---

## Batch usage

```powershell
# Preflight check: tools, each subject's files, disk space
python run_pipeline.py --config config.yaml --check

# Process everyone
python run_pipeline.py --config config.yaml

# A subset
python run_pipeline.py --config config.yaml --subjects sub-001 sub-002

# Re-run some stages after a change
python run_pipeline.py --config config.yaml --force coreg forward
```

Expected layout:

```
dicom_root/
  sub-001/            <- one folder per subject, DICOM inside (recursive)
digitisation/
  sub-001_electrodes.elc
```

Recognized digitization formats: `.fif`, `.hsp`/`.elp` (Polhemus), `.bvct`
(CapTrak), `.sfp`, `.elc`, `.hpts`, `.csd`, `.xyz`. EEG formats: `.edf`, `.bdf`,
`.vhdr` (BrainVision), `.set` (EEGLAB), `.fif`, `.mff`, `.eeg`.

### Resume and cache

Each stage records a fingerprint of its inputs in
`derivatives/<subject>/status.json`. Re-running only recomputes what changed —
and above all does not re-run the ~1.5 h of `charm` needlessly.

### Fault tolerance

`continue_on_error` guards against exceptions; and if a worker **process** dies
(typically the OOM killer on `charm`, 4-8 GB), the batch detects it and **replays
sequentially** instead of losing everything. The real fix remains lowering
`run.n_jobs`.

---

## Quality control

One HTML report per subject (`derivatives/<subject>/qc/`) and a batch summary,
with the metrics, the coregistration residual and the 3D alignment figure.

**Look at the electrode/scalp alignment before using the results.** A low
dig→scalp residual does not guarantee a good fit: on a smooth scalp, the ICP can
slide by a centimeter while keeping the points near the surface. What pins the fit
is the fiducials — which `charm` provides in subject space.

Manual rework of a flagged subject:

```powershell
conda activate mri2mne
mne coreg --subject sub-001 --subjects-dir D:\data\derivatives\subjects
```

Save the corrected fiducials to
`subjects/<subject>/bem/<subject>-fiducials.fif`, then re-run with
`--force coreg forward`.

---

## Source visualization

The source space comes from SimNIBS (the *central* cortical surface), not from
FreeSurfer — but MNE's `stc.plot()` expects a `subjects_dir/<subject>/surf/lh.white`
tree. The `mri2mne.viz` module provides the **bridge**: it writes the SimNIBS mesh
(`-src.fif`) once in FreeSurfer format, after which **all of MNE's native 3D
tooling** (mouse-rotatable window, time slider, movies, ROI time courses) works as
is. It's MNE + SimNIBS, therefore citable, with no home-grown rendering code.

**Interactive window** (rotate/zoom/time with the mouse), from a script:

```powershell
conda activate mri2mne
python examples/open_source_viewer.py D:/derivatives patient01 --time 0.1
```

or in Python:

```python
from mri2mne.viz import open_viewer, block_on_viewer
brain = open_viewer("D:/derivatives", "patient01", initial_time=0.1)
block_on_viewer()   # keeps the window open until it is closed
```

**Static figure** (*offscreen* rendering, for a report or a headless machine):

```python
from pathlib import Path
from mri2mne.paths import SubjectPaths
from mri2mne.viz import save_views

paths = SubjectPaths("patient01", Path("D:/derivatives"),
                     Path("D:/derivatives/subjects"))
save_views(paths, "patient01_sources.png", initial_time=0.1,
           views=("lateral", "medial", "dorsal"), hemi="lh")
```

The API: `write_freesurfer_surfaces(paths)` (the bridge, idempotent),
`plot_sources(paths, ...)` (returns an `mne.viz.Brain`), `open_viewer(...)`
(shortcut from `output_dir`+`subject`), `save_views(...)` (multi-view PNG).

> `surface="inflated"` is identical to `white` (SimNIBS does not inflate the
> surfaces). For the standard smooth *inflated* brain, morph to `fsaverage`
> (`morph_to_fsaverage`) then plot with `subject="fsaverage"`.

---

## What has been validated

Pipeline run **end to end via the public wrapper** on MNE's `sample` dataset
(real anatomy, real EEG in EDF), `status: ok`:

| Check | Result |
|---|---|
| Coregistration (mesh frame, MNE) | median residual **1.85 mm** |
| FEM forward | **10000 cortical sources × 60 channels**, finite gain |
| EEG | 17 left-auditory epochs averaged (EDF) |
| dSPM inverse | operator + estimate OK |
| Output | `sample-lh.stc` / `-rh.stc` |
| Peak (left auditory stim.) | **left hemisphere**, lateral (−55, −35, 34) mm |

The peak is left-lateral, anatomically plausible for an auditory response.

**Also validated on a real clinical DICOM** (T1w series, 384 slices, 0.7 mm): the
full `reconstruct_sources(dicom_dir=...)` chain — anonymization → conversion →
`charm` on the T1 from the DICOM → mesh → coreg → FEM leadfield → dSPM — runs
without a hitch, `status: ok`, cortical output `-lh/-rh.stc`. The EEG used was
deliberately unrelated (validation of the *plumbing*, not of the localization).
**Net** compute time measured on this machine (single-threaded): `charm` ≈ 2 h on
this high-resolution T1, FEM leadfield ≈ 18 min, the rest < 1 min.

**Not validated for lack of data:** a DICOM + **real digitization**
(Polhemus/CapTrak) pair from the **same** subject. Do a first pass on **one
subject** before the batch.

To replay the validation (requires a `charm` output):

```powershell
python examples/run_full_pipeline_sample.py <path-to-m2m_sampleE2E> <scratch>
```

---

## Limitations to know

**Two source frames depending on the route.** The FEM route (default) places the
sources on the cortical surface (mid gray matter, lh+rh); the BEM route
(`head_model: bem`) places them in the volume. Both are documented, publishable
methods; choose according to your analysis.

**Coregistration is the weak link, not the anatomy.** With careful digitization
and a visual check of the alignment, you are fine. Without digitization, accuracy
drops.

**A T2 image improves the skull.** If your protocols include one, set
`simnibs.t2_template`.

**Compute cost.** The FEM leadfield solves one system per electrode on a mesh of
~800k nodes. For 60-256 electrodes, count 20 min to ~2 h. On Windows, the solver
runs in a single process (`fem.cpus` forced to 1: SimNIBS's parallelization is not
picklable with Windows's `spawn`).

---

## Tests

```powershell
conda activate mri2mne
pytest tests -q
```

The tests cover the config, DICOM ingestion (series scorer), EEG reading / the
montage, peak localization, the preflight checks, the wrapper argument validation
and the SimNIBS→FreeSurfer bridge of the visualization. The heavy stages (charm,
FEM leadfield) are validated by `examples/run_full_pipeline_sample.py` on real
data.

---

## Structure

```
run_pipeline.py            Batch CLI entry point
config.example.yaml        Commented configuration
environment.yml            mri2mne environment (driver)
src/mri2mne/
  config.py                YAML loading and validation
  paths.py                 Subject tree + stage cache
  anonymize.py             DICOM PHI + optional defacing
  dicom_convert.py         DICOM → NIfTI + T1 series selection
  headmodel.py             charm wrapper
  coregistration.py        Digitization + ICP (MNE Coregistration)
  simnibs_mesh.py          Scalp + fiducial extraction from the mesh (driver)
  simnibs_forward.py       SimNIBS FEM forward (driver)
  _simnibs_fem_helper.py   Leadfield + make_forward (runs in simnibs_env)
  _simnibs_mesh_helper.py  crop_mesh + fiducials (runs in simnibs_env)
  eeg.py                   EEG reading, preprocessing, covariance
  inverse.py               Inverse operator + source estimate (surface)
  viz.py                   SimNIBS→FreeSurfer bridge + MNE 3D visualization
  wsl.py                   WSL2 bridge (volumetric route): paths, runner, probe
  freesurfer_bem.py        autorecon1 + watershed via WSL (volumetric route)
  volumetric.py            3-layer BEM + source space + volumetric forward/inverse
  wrapper.py               reconstruct_sources[/_volumetric]() : MRI+EEG -> sources
  preflight.py             Checks before launching the batch
  qc.py                    HTML reports
  pipeline.py              Per-subject orchestration (batch)
  batch.py                 Subject discovery + parallelism
examples/
  run_full_pipeline_sample.py   Surface end-to-end validation on real data
  run_volumetric_sample.py      Volumetric route (BEM/WSL) end-to-end
  open_source_viewer.py         Interactive 3D window for a processed subject
```
