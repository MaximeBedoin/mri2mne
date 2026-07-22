"""DICOM MRI to MNE-Python cortical source-analysis pipeline.

Windows-native, no FreeSurfer. The head model, FEM leadfield and cortical
source space come from SimNIBS (`charm`, `compute_tdcs_leadfield`,
`make_forward`); coregistration and the inverse come from MNE.
"""

__version__ = "0.1.0"

STAGES = ("convert", "headmodel", "coreg", "forward", "qc")
