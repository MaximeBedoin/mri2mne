"""PHI removal for DICOM headers, plus optional geometric defacing.

Two separate concerns, deliberately kept apart:

* `anonymize_dicom_dir` strips identifying header tags. This is cheap, exact
  and always worth doing.
* `deface_nifti` removes the face from the reconstructed volume. This one is a
  geometric heuristic, not a validated tool -- it is off by default and the QC
  figure exists so a human can confirm it actually worked.

Neither replaces your institution's data-governance process.
"""

from __future__ import annotations

import logging
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError

# Tags carrying direct identifiers. Emptied rather than deleted, because some
# converters choke on a missing PatientName/PatientID.
_BLANK_TAGS = [
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientMotherBirthName",
    "OtherPatientIDs",
    "OtherPatientNames",
    "ReferringPhysicianName",
    "ReferringPhysicianTelephoneNumbers",
    "PerformingPhysicianName",
    "NameOfPhysiciansReadingStudy",
    "OperatorsName",
    "RequestingPhysician",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "AccessionNumber",
    "StudyID",
    "MedicalRecordLocator",
    "InsurancePlanIdentification",
]

# Tags removed outright: free-text fields where identifiers routinely hide.
_DELETE_TAGS = [
    "PatientComments",
    "StudyComments",
    "AdditionalPatientHistory",
    "MilitaryRank",
    "EthnicGroup",
    "Occupation",
    "RequestAttributesSequence",
    "ReferencedPatientSequence",
]


def anonymize_dicom_dir(
    src_dir: Path,
    dst_dir: Path,
    pseudonym: str,
    logger: logging.Logger,
) -> Path:
    """Copy `src_dir` to `dst_dir`, stripping PHI and setting `pseudonym`.

    The source tree is never modified. Files that are not valid DICOM are
    skipped with a warning rather than aborting the subject: exports commonly
    carry stray DICOMDIR or README files.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    n_skipped = 0

    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        try:
            ds = pydicom.dcmread(str(src), force=False)
        except (InvalidDicomError, OSError):
            n_skipped += 1
            continue

        for tag in _BLANK_TAGS:
            if tag in ds:
                setattr(ds, tag, "")
        for tag in _DELETE_TAGS:
            if tag in ds:
                delattr(ds, tag)

        ds.PatientName = pseudonym
        ds.PatientID = pseudonym
        # De-identification method, per PS3.3 C.12.1.
        ds.PatientIdentityRemoved = "YES"
        ds.DeidentificationMethod = "mri2mne basic header de-identification"

        # Private tags are vendor-defined and may carry anything; drop them.
        ds.remove_private_tags()

        rel = src.relative_to(src_dir)
        out = dst_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        ds.save_as(str(out))
        n_ok += 1

    if n_ok == 0:
        raise RuntimeError(
            f"No readable DICOM files found under {src_dir}. "
            "Check that the subject folder contains an image series."
        )
    logger.info("Anonymised %d DICOM files (%d non-DICOM skipped)", n_ok, n_skipped)
    return dst_dir


def deface_nifti(
    t1_path: Path,
    out_path: Path,
    logger: logging.Logger,
    margin_mm: float = 12.0,
) -> Path:
    """Blank the facial region of a T1, in place of a registration-based tool.

    Writes a *copy*: this must never be the image handed to charm, because the
    cut removes scalp and frontal bone the segmentation depends on. The output
    is for sharing data outside the hospital, nothing else.

    The approach is deliberately crude and conservative. Working in RAS, we
    find the brain's bounding box via a coarse intensity threshold, then zero
    every voxel that is simultaneously anterior to the front of the brain and
    inferior to its centre -- the wedge containing nose, mouth and chin. The
    brain itself is never touched because it is excluded by construction.

    This will not defeat a determined attacker and it is not a substitute for
    `pydeface`. Look at the QC figure before releasing anything.
    """
    img = nib.load(str(t1_path))
    data = np.asarray(img.dataobj, dtype=np.float32)

    # Voxel -> RAS, so the wedge is defined anatomically rather than per-axis.
    affine = img.affine
    shape = data.shape
    idx = np.indices(shape).reshape(3, -1)
    ras = (affine[:3, :3] @ idx + affine[:3, 3:4]).T  # (N, 3) x=R y=A z=S

    # Coarse head/brain estimate: everything above a fraction of the robust max.
    thresh = 0.25 * float(np.percentile(data[data > 0], 99)) if np.any(data > 0) else 0.0
    head = data.reshape(-1) > thresh
    if not head.any():
        logger.warning("Defacing skipped: could not threshold a head from the T1")
        nib.save(img, str(out_path))
        return out_path

    head_ras = ras[head]
    # The brain sits in the middle of the head in y and above centre in z; use
    # percentiles so a bright nose tip or neck cannot drag the estimate.
    brain_front_y = float(np.percentile(head_ras[:, 1], 90))
    brain_centre_z = float(np.percentile(head_ras[:, 2], 55))

    face = (ras[:, 1] > brain_front_y - margin_mm) & (ras[:, 2] < brain_centre_z)
    n_removed = int(face.sum())
    data.reshape(-1)[face] = 0.0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, affine, img.header), str(out_path))
    logger.info(
        "Defaced T1: zeroed %d voxels anterior to y=%.1f and below z=%.1f (RAS mm)",
        n_removed,
        brain_front_y - margin_mm,
        brain_centre_z,
    )
    return out_path
