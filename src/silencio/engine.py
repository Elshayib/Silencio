"""Gapless system-passthrough engine (ticket 01).

Single tested seam: mixed stereo PCM block in, Vocal-plus-SFX stereo PCM
block out. Ticket 01 carries no separation yet, so the ON path defaults to
a bit-perfect passthrough; a pluggable ``processor`` hook lets tickets 02/03
plug the causal separator behind the same seam without changing toggle,
ramp, persistence, or device-recovery behaviour.

Gapless toggle: ``set_enabled()`` starts a linear crossfade of
``ramp_samples`` (default 480 frames = 10ms at 48kHz, budget 50ms) between
the bypass mix and the processed mix. Steady-state OFF and steady-state ON
(with the default passthrough) are both bit-perfect with unity gain, so
loudness parity holds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Union

import numpy as np
from numpy.typing import NDArray

from silencio.state import ToggleStateStore

SAMPLE_RATE: int = 48000
NUM_CHANNELS: int = 2
MAX_SWITCH_SAMPLES_50MS: int = 2400  # 48kHz * 0.050s

Float32Stereo = NDArray[np.float32]
ProcessorFn = Callable[[Float32Stereo], Float32Stereo]


def _passthrough(mixed: Float32Stereo) -> Float32Stereo:
    return np.array(mixed, dtype=np.float32, copy=True)


class SilencioEngine:
    """Stereo 48kHz passthrough with a gapless global toggle."""

    def __init__(
        self,
        processor: ProcessorFn | None = None,
        state_store: ToggleStateStore | None = None,
        sample_rate: int = SAMPLE_RATE,
        ramp_samples: int = 480,
    ) -> None:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"v1 supports only {SAMPLE_RATE}Hz, got {sample_rate}")
        if not 1 <= ramp_samples <= MAX_SWITCH_SAMPLES_50MS:
            raise ValueError(
                f"ramp_samples must be 1..{MAX_SWITCH_SAMPLES_50MS}, got {ramp_samples}"
            )
        self._processor: ProcessorFn = processor if processor is not None else _passthrough
        self._state_store = state_store
        self._sample_rate = sample_rate
        self._ramp_samples = int(ramp_samples)
        initial = bool(state_store.load()) if state_store is not None else False
        self._enabled = initial
        # Crossfade position: 0.0 = full bypass, 1.0 = full processed.
        self._mix: float = 1.0 if initial else 0.0
        self._target: float = 1.0 if initial else 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def num_channels(self) -> int:
        return NUM_CHANNELS

    @property
    def ramp_samples(self) -> int:
        return self._ramp_samples

    @property
    def switch_time_ms(self) -> float:
        return float(self._ramp_samples) / float(self._sample_rate) * 1000.0

    def set_enabled(self, on: bool) -> None:
        target = 1.0 if bool(on) else 0.0
        self._enabled = bool(on)
        self._target = target
        # No snap: process_block() ramps _mix toward _target sample by sample.
        if self._state_store is not None:
            self._state_store.save(self._enabled)

    def reset_for_device_change(self) -> None:
        """Recover from headphone unplug/replug without a restart.

        Keeps the user-visible toggle, drops any mid-ramp transient by
        settling immediately on the target path. The audio graph reopens
        WASAPI streams around this call, and that reopen gap masks the
        settle; the gapless ramp requirement applies to toggle flips on a
        live stream, not to device replugs.
        """
        self._mix = self._target

    def process_block(self, mixed: Union[NDArray[np.float32], NDArray[np.generic]]) -> Float32Stereo:
        arr = np.asarray(mixed)
        if arr.ndim != 2 or arr.shape[1] != NUM_CHANNELS:
            raise ValueError(
                f"expected stereo block (frames, {NUM_CHANNELS}), got shape {arr.shape}"
            )
        if arr.shape[0] == 0:
            raise ValueError("expected non-empty block")
        bypass = np.asarray(arr, dtype=np.float32)
        processed = np.asarray(self._processor(bypass), dtype=np.float32)
        if processed.shape != bypass.shape:
            raise ValueError(
                f"processor must preserve shape {bypass.shape}, got {processed.shape}"
            )

        frames = int(bypass.shape[0])
        # Fast path: steady state, no ramp in flight -> bit-perfect copy.
        if self._mix == self._target:
            source = bypass if self._target == 0.0 else processed
            # Target ON honours the processor so a future separator takes
            # effect once plugged in; target OFF is the untouched mix.
            return np.array(source, dtype=np.float32, copy=True)

        out = np.empty_like(bypass)
        mix = self._mix
        step = 1.0 / float(self._ramp_samples)
        target = self._target
        for i in range(frames):
            if mix < target:
                mix = target if mix + step >= target else mix + step
            elif mix > target:
                mix = target if mix - step <= target else mix - step
            m = float(mix)
            # Linear crossfade keeps consecutive samples continuous even when
            # bypass and processed differ (no pop/click on mid-sound flips).
            out[i] = bypass[i] * (1.0 - m) + processed[i] * m
            if mix == target:
                # Remaining frames are steady-state; bulk-copy them.
                if i + 1 < frames:
                    source = bypass if target == 0.0 else processed
                    out[i + 1 :] = source[i + 1 :]
                break
        self._mix = float(mix)
        return out
