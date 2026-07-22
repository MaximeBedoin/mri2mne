> 🌍 [Français](README.md) · **English**

# Example data

Two demonstration patients, to show the **data layout** and to run the pipeline
(single run and batch). Per-patient structure:

```
data/
  patient01/
    dicom/                 # T1w MRI series in DICOM (384 slices)
    patient01_eeg.edf      # EEG recording
    patient01_dig.fif      # electrode digitization
    patient01-eve.fif      # events (for epoching)
  patient02/               # same structure (to demonstrate the batch)
    ...
```

The analysis outputs are stored in **subfolders of the patient**:

```
  patient01/
    surface/               # surface route output (FEM)  -> .../patient01/mne/patient01-lh.stc
    volumetric/            # volumetric route output (BEM) -> .../patient01/mne/patient01-vol-vl.stc
```

The exact commands (surface + volumetric, single run + batch) are in the
[main README](../README.en.md), section "End-to-end example".

## Provenance and disclaimer

- **DICOM**: anonymized public dataset (`datalad/example-dicom-structural`,
  `PatientIdentityRemoved=YES`). A real structural T1w MRI.
- **EEG + digitization**: MNE-Python `sample` dataset — a **different subject**
  from the MRI. These are **stand-ins** to illustrate the structure and the
  commands; the EEG is not matched to this anatomy, so **the result has no
  clinical meaning**. For a real subject, the EEG and the digitization must come
  from the **same** patient as the MRI.
- `patient02` is a copy of `patient01`, only to demonstrate the batch.

> Note: the volumetric route (BEM) may **flag** this particular clinical T1
> (self-intersecting watershed skull surfaces) — this is the expected behavior on
> certain atypical acquisitions (see the main README).
