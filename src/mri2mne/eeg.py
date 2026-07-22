"""Load and prepare the EEG recording for source analysis.

The anatomy half of the pipeline produces a forward model; this half brings in
the actual EEG (EDF and friends), so that the two can be combined into an
inverse operator and, finally, source estimates.

The electrode positions come from the digitisation, not the EEG file: EDF in
particular stores no coordinates. The digitisation channel labels must match
the EEG channel labels, and mismatches are reported rather than silently
dropped.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np


class EEGError(RuntimeError):
    """Raised when the EEG cannot be read or prepared."""


# Extension -> MNE reader. EDF is the headline format; the rest come for free.
_READERS = {
    ".edf": "read_raw_edf",
    ".bdf": "read_raw_bdf",
    ".gdf": "read_raw_gdf",
    ".vhdr": "read_raw_brainvision",
    ".set": "read_raw_eeglab",
    ".fif": "read_raw_fif",
    ".mff": "read_raw_egi",
    ".eeg": "read_raw_nihon",  # Nihon Kohden; BrainVision uses .vhdr
}


def read_eeg(path: Path, logger: logging.Logger):
    """Read a continuous EEG recording into an MNE Raw, EEG channels only."""
    import mne

    if not path.is_file():
        raise EEGError(f"EEG file not found: {path}")

    reader_name = _READERS.get(path.suffix.lower())
    if reader_name is None:
        raise EEGError(
            f"Unsupported EEG format '{path.suffix}' for {path}. Supported: "
            f"{', '.join(sorted(_READERS))}"
        )

    reader = getattr(mne.io, reader_name)
    logger.info("Reading EEG %s via %s", path.name, reader_name)
    try:
        raw = reader(str(path), preload=True, verbose="ERROR")
    except Exception as exc:  # noqa: BLE001 - readers raise many types
        raise EEGError(f"Failed to read {path}: {exc}") from exc

    # Keep EEG only. Clinical EDF often carries ECG/EOG/trigger channels that
    # would otherwise pollute the covariance and the inverse.
    picks = mne.pick_types(raw.info, eeg=True, meg=False, exclude=[])
    if len(picks) == 0:
        raise EEGError(
            f"{path} contains no EEG channels (found types: "
            f"{set(raw.get_channel_types())})."
        )
    raw.pick("eeg")
    logger.info("EEG: %d channels, %.1f s at %.0f Hz",
                len(raw.ch_names), raw.times[-1], raw.info["sfreq"])
    return raw


def attach_montage(raw, montage, logger: logging.Logger, on_mismatch: str = "warn"):
    """Attach digitised electrode positions to the EEG.

    The digitisation and the EEG were recorded separately, so their channel
    labels can disagree (case, 'FP1' vs 'Fp1', extra channels). We align what
    we can and report the rest instead of failing outright.
    """
    import mne

    eeg_names = set(raw.ch_names)
    montage_names = set(montage.ch_names)

    matched = eeg_names & montage_names
    if not matched:
        # Try a case-insensitive rescue before giving up.
        lower = {n.lower(): n for n in montage.ch_names}
        rename = {n: lower[n.lower()] for n in raw.ch_names if n.lower() in lower}
        if rename:
            raw.rename_channels(rename)
            matched = set(raw.ch_names) & montage_names
    if not matched:
        raise EEGError(
            "No EEG channel label matches the digitisation. EEG has e.g. "
            f"{sorted(eeg_names)[:5]}, digitisation has {sorted(montage_names)[:5]}. "
            "Rename channels so they agree."
        )

    missing = sorted(set(raw.ch_names) - montage_names)
    if missing:
        message = (
            f"{len(missing)} EEG channel(s) have no digitised position and will "
            f"be dropped: {missing[:8]}"
        )
        if on_mismatch == "raise":
            raise EEGError(message)
        logger.warning(message)
        raw.drop_channels(missing)

    raw.set_montage(montage, on_missing="raise", match_case=False)
    logger.info("Attached montage: %d electrodes positioned", len(raw.ch_names))
    return raw


def preprocess(raw, l_freq: float | None, h_freq: float | None,
               set_reference: str | None, logger: logging.Logger):
    """Band-pass and (re)reference. EEG source modelling needs an average
    reference expressed as a projection so the forward and data agree."""
    if l_freq is not None or h_freq is not None:
        logger.info("Filtering %s-%s Hz", l_freq, h_freq)
        raw.filter(l_freq, h_freq, verbose="ERROR")

    if set_reference == "average":
        # projection=True so the reference is applied consistently wherever the
        # inverse is computed, rather than baked into the data here.
        raw.set_eeg_reference("average", projection=True, verbose="ERROR")
        logger.info("Set average EEG reference (as projection)")
    elif set_reference:
        raw.set_eeg_reference([set_reference], verbose="ERROR")
        logger.info("Referenced to %s", set_reference)
    return raw


def build_evoked(
    raw,
    events,
    event_id,
    tmin: float,
    tmax: float,
    baseline,
    reject,
    logger: logging.Logger,
):
    """Epoch around events and average into an Evoked.

    Returns (evoked, epochs). When no events are supplied the whole recording
    is treated as one pseudo-epoch, which is the sensible default for localising
    an already-averaged response or a hand-cut segment.
    """
    import mne

    if events is None:
        logger.info("No events given; treating the whole recording as one epoch")
        epochs = mne.make_fixed_length_epochs(raw, duration=raw.times[-1],
                                              preload=True, verbose="ERROR")
        evoked = epochs.average()
        return evoked, epochs

    events = np.asarray(events)
    epochs = mne.Epochs(
        raw, events, event_id=event_id, tmin=tmin, tmax=tmax,
        baseline=baseline, reject=reject, preload=True, verbose="ERROR",
    )
    if len(epochs) == 0:
        raise EEGError(
            "No epochs survived rejection. Loosen `reject` or check the events."
        )
    evoked = epochs.average()
    logger.info("Averaged %d epoch(s) -> evoked, %d channels, peak at %.3f s",
                len(epochs), len(evoked.ch_names),
                evoked.times[np.argmax(np.abs(evoked.data).max(axis=0))])
    return evoked, epochs


def compute_noise_cov(
    epochs_or_raw,
    tmin: float | None,
    tmax: float | None,
    logger: logging.Logger,
):
    """Estimate the sensor noise covariance.

    From the pre-stimulus baseline of the epochs when available (the standard
    choice), otherwise from a quiet stretch of raw. The covariance is what tells
    the inverse how much to trust each channel; a bad one skews localisation.
    """
    import mne

    if isinstance(epochs_or_raw, mne.BaseEpochs):
        logger.info("Noise covariance from epochs baseline (%s to %s s)", tmin, tmax)
        cov = mne.compute_covariance(
            epochs_or_raw, tmin=tmin, tmax=tmax, method="auto", verbose="ERROR",
        )
    else:
        logger.info("Noise covariance from raw (%s to %s s)", tmin, tmax)
        cov = mne.compute_raw_covariance(
            epochs_or_raw, tmin=tmin, tmax=tmax, method="auto", verbose="ERROR",
        )
    logger.info("Noise covariance: rank %s over %d channels",
                cov.get('nfree', '?'), cov['dim'])
    return cov
