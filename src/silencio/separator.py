"""Streaming causal separator behind the engine buffer seam (ticket 02).

The separator takes mixed stereo PCM blocks in and emits Vocal-plus-SFX
stereo PCM blocks out, preserving the stereo image. It is a lightweight
CPU-only causal algorithm (no model weights, no network, fully local per
ADR-0002/ADR-0003), designed for the fail-open ambiguity policy: on unsure
frames it leaks Music rather than clipping Vocal.

How it separates (all features causal: past and current input only):

- Per-bin stereo width (side/mid power ratio): centered Vocal measures
  near 0, panned-but-correlated SFX measures small, while wide Music pads
  and diffuse crowd/choir measure near 1. Static tones defeat smoothed
  coherence estimates, but the instantaneous side/mid ratio still
  separates them.
- Per-bin sustainedness (slow/fast power ratio): steady pad bins cut,
  modulated Vocal bins stay.
- Per-bin transient onsets with chronic-fire gating: sparse SFX onsets
  punch through (kept), while constantly refiring beating partials lose
  onset eligibility so triggered pumping cannot expand steady Music.
- Scalar syllable-rate modulation (envelope variation) and sustained-bass
  followers handle narrow centered Music in Vocal gaps; a scalar flux /
  energy-jump backstop keeps broadband onsets.
- Suppression gains move slowly downward and instantly upward, so cuts
  fade in over ~100ms (no clicks, no pumping) while onsets pass at once.

Fixed latency is one frame (1024 samples = 21.3ms at 48kHz), inside the
150ms end-to-end budget. Identical gains apply to both channels, so the
stereo image is preserved exactly.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE: int = 48000
NUM_CHANNELS: int = 2
FRAME_SIZE: int = 1024
HOP_SIZE: int = 256
LATENCY_SAMPLES: int = FRAME_SIZE  # 21.3ms at 48kHz

Float32Stereo = NDArray[np.float32]

_WINDOW: NDArray[np.float64] = np.hanning(FRAME_SIZE + 1)[:-1].astype(np.float64)
_WINDOW_SQ: NDArray[np.float64] = _WINDOW**2
_FREQS = np.fft.rfftfreq(FRAME_SIZE, 1.0 / float(SAMPLE_RATE))
_NBINS: int = int(_FREQS.shape[0])

_SUB_EDGE: float = 60.0  # below: scalar sustained cut (LFE/rumble zone)
_BASS_EDGE: float = 200.0  # below: no Vocal brilliance; per-bin logic still applies above _SUB_EDGE
_MID_TOP: float = 4000.0  # above: unity (SFX air and Vocal sibilance always pass)
_SUB_MASK: NDArray[np.bool_] = _FREQS < _SUB_EDGE
_BASS_MASK: NDArray[np.bool_] = _FREQS < _BASS_EDGE
_MID_MASK: NDArray[np.bool_] = (_FREQS >= _BASS_EDGE) & (_FREQS < _MID_TOP)
_LOW_MASK: NDArray[np.bool_] = (_FREQS >= _SUB_EDGE) & (_FREQS < _BASS_EDGE)

_EMIT_FLOOR: float = 1e-12


def _one_pole_coeff(tau_seconds: float) -> float:
    return 1.0 - float(np.exp(-HOP_SIZE / (SAMPLE_RATE * tau_seconds)))


class CausalSeparator:
    """Lightweight streaming separator: mixed stereo in, Vocal-plus-SFX stereo out."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        ring_size: int = 32768,
        music_depth: float = 0.75,
    ) -> None:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"v1 supports only {SAMPLE_RATE}Hz, got {sample_rate}")
        if ring_size < 4 * FRAME_SIZE + 8192:
            raise ValueError(f"ring_size must be >= {4 * FRAME_SIZE + 8192}, got {ring_size}")
        if not 0.0 < music_depth <= 1.0:
            raise ValueError(f"music_depth must be 0..1, got {music_depth}")
        self._sample_rate = sample_rate
        self._ring_size = int(ring_size)
        self._music_depth = float(music_depth)
        self._reset_state()

    def _reset_state(self) -> None:
        self._ola = np.zeros((self._ring_size, NUM_CHANNELS), dtype=np.float64)
        self._wsum = np.zeros(self._ring_size, dtype=np.float64)
        self._inbuf = np.zeros((0, NUM_CHANNELS), dtype=np.float64)
        self._consumed = 0  # absolute index of _inbuf[0]
        self._frame_pos = 0  # absolute index of next frame start
        self._fed = 0  # total input samples accepted
        self._prev_mag: NDArray[np.float64] | None = None
        # Per-bin smoothed statistics (fail-open inits: coherent, quiet).
        self._side = np.zeros(_NBINS, dtype=np.float64)
        self._mid = np.ones(_NBINS, dtype=np.float64) * 1e-6
        self._slow_p = np.ones(_NBINS, dtype=np.float64) * 1e-6
        self._fast_p = np.ones(_NBINS, dtype=np.float64) * 1e-6
        self._fire_rate = np.zeros(_NBINS, dtype=np.float64)
        self._gains = np.ones(_NBINS, dtype=np.float64)
        self._trans_hold = np.zeros(_NBINS, dtype=np.int32)
        self._scalar_hold = 0
        self._hops = 0
        # Scalar followers.
        self._fast_mid = 0.0
        self._slow_mid = 0.0
        self._fast_bass = 0.0
        self._slow_bass = 0.0
        self._slow_tot = 0.0
        self._bass_gain = 1.0
        self._env_hist: list[float] = []

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def num_channels(self) -> int:
        return NUM_CHANNELS

    @property
    def music_depth(self) -> float:
        return self._music_depth

    @property
    def latency_samples(self) -> int:
        return LATENCY_SAMPLES

    def reset(self) -> None:
        """Drop all streaming state (device-change recovery without restart)."""
        self._reset_state()

    def __call__(self, mixed: Float32Stereo) -> Float32Stereo:
        return self.process_block(mixed)

    def process_block(self, mixed: Float32Stereo) -> Float32Stereo:
        """Process one stereo block; input and output share shape and dtype."""
        arr = np.asarray(mixed)
        if arr.ndim != 2 or arr.shape[1] != NUM_CHANNELS:
            raise ValueError(
                f"expected stereo block (frames, {NUM_CHANNELS}), got shape {arr.shape}"
            )
        if arr.shape[0] == 0:
            raise ValueError("expected non-empty block")
        block = arr.astype(np.float64)
        frames = int(block.shape[0])
        self._inbuf = np.concatenate([self._inbuf, block], axis=0)
        self._fed += frames
        while self._frame_pos + FRAME_SIZE <= self._consumed + self._inbuf.shape[0]:
            self._process_frame()
        # Fixed-lag emission: output sample j carries input sample j and is
        # complete once fed >= j + FRAME_SIZE. Leading negative slots emit
        # silence (priming); every call still returns exactly len(block).
        first = self._fed - frames - LATENCY_SAMPLES
        out = np.zeros((frames, NUM_CHANNELS), dtype=np.float64)
        lo = max(first, 0)
        hi = min(first + frames, self._fed - FRAME_SIZE)
        if hi > lo:
            out[lo - first : hi - first] = self._emit(lo, hi - lo)
        if self._frame_pos - self._consumed > 3 * FRAME_SIZE:
            drop = self._frame_pos - self._consumed - 2 * FRAME_SIZE
            self._inbuf = self._inbuf[drop:]
            self._consumed += drop
        return out.astype(np.float32)

    def flush(self) -> Float32Stereo:
        """Drain the pipeline tail after the final input block (offline use)."""
        return self.process_block(np.zeros((LATENCY_SAMPLES, NUM_CHANNELS), dtype=np.float32))

    def _process_frame(self) -> None:
        rel = self._frame_pos - self._consumed
        frame = self._inbuf[rel : rel + FRAME_SIZE]
        mono = (frame[:, 0] + frame[:, 1]) / 2.0
        spec_l = np.fft.rfft(frame[:, 0] * _WINDOW)
        spec_r = np.fft.rfft(frame[:, 1] * _WINDOW)
        mag = np.abs(np.fft.rfft(mono * _WINDOW))
        power = mag**2

        # Stereo width: side/mid power ratio per bin (instantaneous, smoothed).
        width_alpha = _one_pole_coeff(0.50)
        side = np.abs(spec_l - spec_r) ** 2
        mid = np.abs(spec_l + spec_r) ** 2
        self._side += width_alpha * (side - self._side)
        self._mid += width_alpha * (mid - self._mid)
        width = self._side / (self._mid + 1e-18)

        # Sustainedness: slow/fast power ratio per bin.
        fast_alpha = _one_pole_coeff(0.015)
        slow_alpha = _one_pole_coeff(0.80)
        self._fast_p += fast_alpha * (power - self._fast_p)
        self._slow_p += slow_alpha * (power - self._slow_p)
        sustained = np.clip(self._slow_p / (self._fast_p + 1e-18) - 0.85, 0.0, 1.0) / 0.6
        sustained = np.clip(sustained, 0.0, 1.0)
        sustained *= np.clip((self._slow_p - 1e-9) / 1e-9, 0.0, 1.0)

        # Per-bin transient onsets; chronic firers (beating partials) lose
        # eligibility so triggered pumping cannot expand steady Music.
        abs_jump = power - self._slow_p
        floor = 1e-5 * (float(np.sum(power)) + 1e-12)
        raw_onset = (power > 5.0 * (self._slow_p + 1e-18)) & (abs_jump > floor)
        self._fire_rate += _one_pole_coeff(1.00) * (
            raw_onset.astype(np.float64) - self._fire_rate
        )
        onset = raw_onset & (self._fire_rate < 0.15)
        self._trans_hold[onset] = 6

        # Scalar followers: speech modulation, sustained bass, flux/jumps.
        bass_energy = float(np.sum(power[_BASS_MASK]))
        mid_energy = float(np.sum(power[_MID_MASK]))
        total_energy = float(np.sum(power)) + 1e-12
        flux = 0.0
        if self._prev_mag is not None:
            flux = float(np.sum(np.clip(mag - self._prev_mag, 0.0, None) ** 2)) / total_energy
        self._prev_mag = mag
        self._fast_mid += _one_pole_coeff(0.010) * (mid_energy - self._fast_mid)
        self._slow_mid += _one_pole_coeff(0.300) * (mid_energy - self._slow_mid)
        self._fast_bass += _one_pole_coeff(0.010) * (bass_energy - self._fast_bass)
        self._slow_bass += _one_pole_coeff(0.500) * (bass_energy - self._slow_bass)
        self._slow_tot += _one_pole_coeff(0.200) * (total_energy - self._slow_tot)
        self._env_hist.append(self._fast_mid)
        if len(self._env_hist) > 40:
            self._env_hist.pop(0)
        variation = 0.0
        if len(self._env_hist) >= 20:
            hist = np.array(self._env_hist, dtype=np.float64)
            variation = float(np.std(hist) / (np.mean(hist) + 1e-12))
        sustained_bass = min(1.0, self._slow_bass / (self._fast_bass + 1e-9))
        jump_mid = mid_energy / (self._slow_mid + 1e-12)
        jump_bass = bass_energy / (self._slow_bass + 1e-12)
        jump_total = total_energy / (self._slow_tot + 1e-12)
        priming = self._hops < 6
        scalar_onset = (not priming) and (
            (flux > 0.22 and jump_total > 2.0) or jump_mid > 3.5 or jump_bass > 4.0
        )
        if scalar_onset:
            self._scalar_hold = 6
        elif self._scalar_hold > 0:
            self._scalar_hold -= 1
        in_transient = self._scalar_hold > 0

        # Sub-bass: scalar sustained cut (Vocal has nothing down here).
        target_bass = 1.0 if in_transient else float(1.0 - 0.90 * min(1.0, max(0.0, sustained_bass)))
        if target_bass > self._bass_gain:
            self._bass_gain += (target_bass - self._bass_gain) * 0.6
        else:
            self._bass_gain += (target_bass - self._bass_gain) * 0.25

        # Per-bin Music confidence: wide/diffuse cuts outright; centered
        # content cuts only when sustained and syllable-calm.
        calm = min(1.0, max(0.0, (0.30 - variation) / 0.18))
        wide = np.clip((width - 0.25) / 0.25, 0.0, 1.0)
        music_bin = np.maximum(wide, sustained * calm)
        target = 1.0 - self._music_depth * music_bin
        keep = (self._trans_hold > 0)
        self._trans_hold[self._trans_hold > 0] -= 1
        target[keep] = 1.0
        if in_transient:
            target[:] = 1.0
            self._bass_gain = 1.0
        rising = target > self._gains
        self._gains[rising] = target[rising]
        self._gains[~rising] += (target[~rising] - self._gains[~rising]) * 0.05

        gains = np.ones_like(mag)
        gains[_SUB_MASK] = self._bass_gain
        gains[_LOW_MASK] = self._gains[_LOW_MASK]
        gains[_MID_MASK] = self._gains[_MID_MASK]
        padded = np.pad(gains, 2, mode="edge")
        gains = np.convolve(padded, np.ones(5) / 5.0, mode="valid")
        self._overlap_add(spec_l, spec_r, gains)
        self._frame_pos += HOP_SIZE
        self._hops += 1

    def _overlap_add(
        self,
        spec_l: NDArray[np.complex128],
        spec_r: NDArray[np.complex128],
        gains: NDArray[np.float64],
    ) -> None:
        out_l = np.fft.irfft(spec_l * gains, FRAME_SIZE) * _WINDOW
        out_r = np.fft.irfft(spec_r * gains, FRAME_SIZE) * _WINDOW
        base = self._frame_pos % self._ring_size
        if base + FRAME_SIZE <= self._ring_size:
            self._ola[base : base + FRAME_SIZE, 0] += out_l
            self._ola[base : base + FRAME_SIZE, 1] += out_r
            self._wsum[base : base + FRAME_SIZE] += _WINDOW_SQ
        else:
            idx = (self._frame_pos + np.arange(FRAME_SIZE)) % self._ring_size
            np.add.at(self._ola[:, 0], idx, out_l)
            np.add.at(self._ola[:, 1], idx, out_r)
            np.add.at(self._wsum, idx, _WINDOW_SQ)

    def _emit(self, first: int, count: int) -> NDArray[np.float64]:
        out = np.zeros((count, NUM_CHANNELS), dtype=np.float64)
        base = first % self._ring_size
        if base + count <= self._ring_size:
            weights = self._wsum[base : base + count]
            acc = self._ola[base : base + count]
            done = weights > _EMIT_FLOOR
            out[done] = acc[done] / weights[done, None]
            self._ola[base : base + count] = 0.0
            self._wsum[base : base + count] = 0.0
        else:
            idx = (first + np.arange(count)) % self._ring_size
            weights = self._wsum[idx]
            acc = self._ola[idx]
            done = weights > _EMIT_FLOOR
            out[done] = acc[done] / weights[done, None]
            self._ola[idx] = 0.0
            self._wsum[idx] = 0.0
        return out
