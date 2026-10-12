"""44.1kHz <-> 48kHz resampling adapter (ticket 03).

The engine buffer seam stays stereo 48kHz-only; this module owns the
input-path resampling the spec requires ("resampling of 44.1kHz
sources") so the live graph can accept 44.1kHz capture blocks, run the
seam internally at 48kHz, and return the caller rate. Numpy-only,
CPU, deterministic, stereo-image preserving (identical per-channel
linear interpolation, no mono downmix).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

SUPPORTED_RATES: tuple[int, ...] = (44100, 48000)
Float32Stereo = NDArray[np.float32]


def _check_rate(rate: int) -> None:
    if rate not in SUPPORTED_RATES:
        raise ValueError(f"v1 resamples only {SUPPORTED_RATES}, got {rate}")


def _check_stereo_block(block: NDArray[np.generic]) -> NDArray[np.float64]:
    arr = np.asarray(block)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"expected stereo block (frames, 2), got shape {arr.shape}")
    return np.asarray(arr, dtype=np.float64)


def resample_stereo(
    block: NDArray[np.generic],
    src_rate: int,
    dst_rate: int,
) -> Float32Stereo:
    """Resample one whole stereo buffer from ``src_rate`` to ``dst_rate``."""
    _check_rate(src_rate)
    _check_rate(dst_rate)
    arr = _check_stereo_block(block)
    if arr.shape[0] == 0:
        raise ValueError("expected non-empty block")
    if src_rate == dst_rate:
        return np.array(arr, dtype=np.float32, copy=True)
    n_in = int(arr.shape[0])
    n_out = int(round(n_in * dst_rate / src_rate))
    if n_out == 0:
        return np.zeros((0, 2), dtype=np.float32)
    step = src_rate / dst_rate
    times = np.arange(n_out, dtype=np.float64) * step
    i0 = np.floor(times).astype(np.int64)
    frac = times - i0.astype(np.float64)
    i0 = np.clip(i0, 0, n_in - 1)
    i1 = np.clip(i0 + 1, 0, n_in - 1)
    f = frac[:, None]
    out = arr[i0] * (1.0 - f) + arr[i1] * f
    return np.asarray(out, dtype=np.float32)


class StreamingResampler:
    """Block-wise resampler that matches :func:`resample_stereo` exactly.

    Feed capture blocks via :meth:`push`; drain the tail with
    :meth:`flush` after the final input. Identical inputs give identical
    outputs regardless of block chunking, so live block sizes never
    change what the listener hears (no boundary clicks beyond the
    linear-interpolation contract).
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        _check_rate(src_rate)
        _check_rate(dst_rate)
        self._src = int(src_rate)
        self._dst = int(dst_rate)
        self._step = float(src_rate) / float(dst_rate)
        self._buf = np.zeros((0, 2), dtype=np.float64)
        self._base = 0  # absolute input index of _buf[0]
        self._next = 0.0  # absolute input time of next output sample
        self._fed = 0
        self._produced = 0

    @property
    def src_rate(self) -> int:
        return self._src

    @property
    def dst_rate(self) -> int:
        return self._dst

    def push(self, block: NDArray[np.generic]) -> Float32Stereo:
        arr = np.asarray(block)
        if arr.ndim != 2 or arr.shape[1] != 2:
            raise ValueError(f"expected stereo block (frames, 2), got shape {arr.shape}")
        if arr.shape[0] == 0:
            return np.zeros((0, 2), dtype=np.float32)
        if self._src == self._dst:
            return np.array(arr, dtype=np.float32, copy=True)
        incoming = np.asarray(arr, dtype=np.float64)
        self._buf = np.concatenate([self._buf, incoming], axis=0)
        self._fed += int(incoming.shape[0])
        emitted: list[NDArray[np.float64]] = []
        while True:
            rel = self._next - float(self._base)
            i0 = int(math.floor(rel))
            frac = rel - float(i0)
            if i0 < 0:
                # Cannot happen (base only advances past consumed input),
                # but guard against float drift by re-basing.
                i0 = 0
                frac = 0.0
            if i0 + 1 >= self._buf.shape[0]:
                break
            row = self._buf[i0] * (1.0 - frac) + self._buf[i0 + 1] * frac
            emitted.append(row)
            self._next += self._step
            self._produced += 1
        drop = int(math.floor(self._next - float(self._base)))
        if drop > 0:
            # Keep the sample the next output interpolates from.
            drop = min(drop, max(0, self._buf.shape[0] - 1))
            if drop > 0:
                self._buf = self._buf[drop:]
                self._base += drop
        if not emitted:
            return np.zeros((0, 2), dtype=np.float32)
        return np.asarray(np.stack(emitted, axis=0), dtype=np.float32)

    def flush(self) -> Float32Stereo:
        if self._src == self._dst:
            return np.zeros((0, 2), dtype=np.float32)
        total_out = int(round(self._fed * self._dst / self._src))
        remaining = total_out - self._produced
        if remaining <= 0 or self._buf.shape[0] == 0:
            return np.zeros((0, 2), dtype=np.float32)
        rows: list[NDArray[np.float64]] = []
        last = self._buf[-1]
        for _ in range(remaining):
            rel = self._next - float(self._base)
            i0 = int(math.floor(rel))
            frac = rel - float(i0)
            if i0 < 0:
                i0 = 0
                frac = 0.0
            if i0 >= self._buf.shape[0]:
                rows.append(last)
            elif i0 + 1 >= self._buf.shape[0]:
                # Final clamped sample (matches whole-buffer edge).
                rows.append(self._buf[i0] * (1.0 - frac) + last * frac)
            else:
                rows.append(self._buf[i0] * (1.0 - frac) + self._buf[i0 + 1] * frac)
            self._next += self._step
            self._produced += 1
        self._buf = np.zeros((0, 2), dtype=np.float64)
        return np.asarray(np.stack(rows, axis=0), dtype=np.float32)
