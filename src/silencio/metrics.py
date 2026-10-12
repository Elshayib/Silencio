"""Measurement helpers for the ticket 02 acceptance clips.

These operate on whole signals (an independent FFT analysis), while the
separator under test works streaming hop-by-hop: the two never share code
paths, so thresholds agreed from the spec stay honest.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def bandpower(signal: NDArray[np.float32], f_lo: float, f_hi: float, sample_rate: int = 48000) -> float:
    """Total power of ``signal`` (mono or stereo sum) between ``f_lo`` and ``f_hi`` Hz."""
    mono = np.asarray(signal, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono[:, 0] + mono[:, 1]
    spectrum = np.fft.rfft(mono)
    freqs = np.fft.rfftfreq(mono.shape[0], 1.0 / float(sample_rate))
    mask = (freqs >= f_lo) & (freqs < f_hi)
    return float(np.sum(np.abs(spectrum[mask]) ** 2))


def total_power(signal: NDArray[np.float32]) -> float:
    """Mean-square power of a stereo block."""
    arr = np.asarray(signal, dtype=np.float64)
    return float(np.mean(arr**2))


def db(after: float, before: float) -> float:
    """Level change in dB from ``before`` to ``after``."""
    return 10.0 * float(np.log10((after + 1e-12) / (before + 1e-12)))


def lr_ratio_db(block: NDArray[np.float32]) -> float:
    """Left/right energy ratio in dB (stereo imaging probe)."""
    arr = np.asarray(block, dtype=np.float64)
    return 10.0 * float(
        np.log10((float(np.sum(arr[:, 0] ** 2)) + 1e-18) / (float(np.sum(arr[:, 1] ** 2)) + 1e-18))
    )


def correlation(first: NDArray[np.float32], second: NDArray[np.float32]) -> float:
    """Zero-mean normalized cross-correlation of two flattened blocks."""
    a = np.asarray(first, dtype=np.float64).ravel()
    b = np.asarray(second, dtype=np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b)) + 1e-18
    return float(np.dot(a, b) / denom)
