"""Deterministic acceptance clips for ticket 02 (offline, no hardware).

Three fixed mixes plus two probes, all stereo 48kHz:

- song: lead Vocal (centered melody with vibrato and syllable motion) over
  a hotter Music bed (centered bass plus a wide sustained pad).
- movie: centered dialogue bursts over a wide low score with a centered root.
- game: centered dialogue plus panned-but-correlated SFX (gunshot,
  footstep, UI blip at known times) over a wide score.
- crowd: diffuse detuned voices plus wash, independent per channel. Per
  the glossary this counts as Music to suppress, never as Vocal.
- unison: Vocal and Music sharing one pitch (ambiguous by construction);
  the Vocal side carries vibrato and syllable motion, the Music side is
  sustained. Fail-open keeps the Vocal here.

Convention: Vocal is centered, Music beds are wide, SFX are
panned-but-correlated (direction cues survive), crowds are diffuse. This
matches real mixes closely enough to judge behavior while staying fully
deterministic (fixed seeds, no audio files).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from silencio.engine import NUM_CHANNELS, SAMPLE_RATE, SilencioEngine
from silencio.separator import LATENCY_SAMPLES

Float32Stereo = NDArray[np.float32]
StemName = Literal["mix", "vocal", "music", "sfx"]

_SETTLE_SAMPLES: int = SAMPLE_RATE  # detector convergence excluded from metrics
_TAIL_SAMPLES: int = SAMPLE_RATE // 10  # OLA edge excluded from metrics

# Score-only probe windows in clip seconds (no Vocal, no SFX there).
MOVIE_SCORE_GAP_S: tuple[float, float] = (2.125, 2.50)
GAME_SCORE_GAP_S: tuple[float, float] = (3.15, 3.35)
# UI blip onset in clip seconds (clean dialogue gap).
GAME_BLIP_S: float = 3.05

_DIALOG_STARTS = (0.15, 0.9625, 1.775, 2.5875, 3.4)
_DIALOG_LENGTH_S = 0.35


@dataclass(frozen=True)
class Clip:
    """A fixed acceptance mix with its reference stems."""

    name: str
    sample_rate: int
    mix: Float32Stereo
    vocal: Float32Stereo
    music: Float32Stereo
    sfx: Float32Stereo | None = None


def _center(mono: NDArray[np.float64]) -> Float32Stereo:
    return np.stack([mono, mono], axis=1).astype(np.float32)


def _harmonic_stack(frames: int, f0: NDArray[np.float64], n_harm: int = 8) -> NDArray[np.float64]:
    out = np.zeros(frames, dtype=np.float64)
    for k in range(1, n_harm + 1):
        phase = 2.0 * np.pi * np.cumsum(f0) / float(SAMPLE_RATE) * float(k)
        out += np.sin(phase) / float(k)
    return out / 2.0


def _wide_pad(frames: int, freqs: tuple[float, ...], seed: int, level: float) -> Float32Stereo:
    """Sustained pad with independent phases per channel (wide, decorrelated)."""
    rng = np.random.default_rng(seed)
    t = np.arange(frames, dtype=np.float64) / float(SAMPLE_RATE)
    out = np.zeros((frames, NUM_CHANNELS), dtype=np.float64)
    for ch in range(NUM_CHANNELS):
        acc = np.zeros(frames, dtype=np.float64)
        for f in freqs:
            acc += np.sin(2.0 * np.pi * f * t + rng.uniform(0.0, 2.0 * np.pi))
            acc += 0.8 * np.sin(2.0 * np.pi * f * 1.004 * t + rng.uniform(0.0, 2.0 * np.pi))
        out[:, ch] = acc
    out *= level / (float(np.sqrt(np.mean(out**2))) + 1e-9)
    return out.astype(np.float32)


def _dialogue(frames: int, seed: int, f0base: float) -> NDArray[np.float64]:
    """Speech-like harmonic bursts with gaps (centered dialogue/lead)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(frames, dtype=np.float64)
    burst_len = int(_DIALOG_LENGTH_S * SAMPLE_RATE)
    for start_s in _DIALOG_STARTS:
        i0 = int(start_s * SAMPLE_RATE)
        i1 = min(frames, i0 + burst_len)
        count = i1 - i0
        if count <= 0:
            continue
        tt = np.arange(count, dtype=np.float64) / float(SAMPLE_RATE)
        wobble = 30.0 * np.sin(2.0 * np.pi * 3.1 * tt + rng.uniform(0.0, 6.0))
        f0 = f0base + wobble + rng.uniform(-8.0, 8.0)
        phase = 2.0 * np.pi * np.cumsum(f0) / float(SAMPLE_RATE)
        burst = np.zeros(count, dtype=np.float64)
        for k in range(1, 7):
            burst += np.sin(phase * float(k) + rng.uniform(0.0, 6.0)) / float(k)
        am = 0.6 + 0.4 * np.sin(2.0 * np.pi * 5.0 * tt + rng.uniform(0.0, 6.0)) ** 2
        attack = np.minimum(1.0, np.arange(count) / (0.02 * SAMPLE_RATE))
        release = np.minimum(1.0, np.arange(count)[::-1] / (0.03 * SAMPLE_RATE))
        out[i0:i1] += burst * am * attack * release
    return out / (float(np.sqrt(np.mean(out**2))) + 1e-9) * 0.5


def make_song_clip(duration_s: float = 4.0) -> Clip:
    """Vocal song with full accompaniment (Music bed 3dB hotter than Vocal)."""
    frames = int(duration_s * SAMPLE_RATE)
    t = np.arange(frames, dtype=np.float64) / float(SAMPLE_RATE)
    notes = np.array([220.0, 277.18, 329.63, 261.63], dtype=np.float64)
    seg = frames // len(notes)
    f0 = np.concatenate([np.full(seg, f) for f in notes])[:frames].copy()
    f0 = np.convolve(f0, np.ones(64) / 64.0, mode="same")
    vibrato = 1.0 + 0.02 * np.sin(2.0 * np.pi * 5.5 * t)
    syllables = 0.65 + 0.35 * np.sin(2.0 * np.pi * 4.0 * t) ** 2
    vocal = _harmonic_stack(frames, f0 * vibrato) * syllables
    vocal *= 0.5 / (float(np.sqrt(np.mean(vocal**2))) + 1e-9)
    bass = 0.9 * np.sin(2.0 * np.pi * 82.41 * t)
    bass_stereo = _center(bass / (float(np.sqrt(np.mean(bass**2))) + 1e-9) * 0.5)
    pad = _wide_pad(frames, (110.0, 164.81, 220.0), seed=3, level=0.5)
    vocal_stereo = _center(vocal).astype(np.float32)
    music = (bass_stereo.astype(np.float64) + pad.astype(np.float64)).astype(np.float32)
    return Clip(
        name="song",
        sample_rate=SAMPLE_RATE,
        mix=(vocal_stereo.astype(np.float64) + music.astype(np.float64)).astype(np.float32),
        vocal=vocal_stereo,
        music=music,
    )


def make_movie_clip(duration_s: float = 4.0) -> Clip:
    """Film dialogue over a wide sustained score."""
    frames = int(duration_s * SAMPLE_RATE)
    vocal = _dialogue(frames, seed=21, f0base=190.0)
    score = _wide_pad(frames, (110.0, 138.59, 165.0), seed=9, level=0.35)
    t = np.arange(frames, dtype=np.float64) / float(SAMPLE_RATE)
    root = 0.3 * np.sin(2.0 * np.pi * 55.0 * t)
    root_stereo = _center(root / (float(np.sqrt(np.mean(root**2))) + 1e-9) * 0.15)
    music = (score.astype(np.float64) + root_stereo.astype(np.float64)).astype(np.float32)
    vocal_stereo = _center(vocal).astype(np.float32)
    return Clip(
        name="movie",
        sample_rate=SAMPLE_RATE,
        mix=(vocal_stereo.astype(np.float64) + music.astype(np.float64)).astype(np.float32),
        vocal=vocal_stereo,
        music=music,
    )


def make_game_clip(duration_s: float = 4.0) -> Clip:
    """Game capture: dialogue plus panned SFX over a wide score.

    SFX times (seconds): gunshot 1.45, footstep 2.30, UI blip 3.05.
    """

    frames = int(duration_s * SAMPLE_RATE)
    vocal = _dialogue(frames, seed=33, f0base=210.0)
    score = _wide_pad(frames, (98.0, 146.8), seed=12, level=0.30)
    sfx = np.zeros((frames, NUM_CHANNELS), dtype=np.float64)
    rng = np.random.default_rng(5)
    i0, length = int(1.45 * SAMPLE_RATE), int(0.09 * SAMPLE_RATE)
    burst = rng.standard_normal(length) * np.exp(-np.arange(length) / (0.012 * SAMPLE_RATE))
    sfx[i0 : i0 + length, 0] += burst * 0.8
    sfx[i0 : i0 + length, 1] += burst * 0.34
    i0, length = int(2.30 * SAMPLE_RATE), int(0.10 * SAMPLE_RATE)
    thump = np.sin(2.0 * np.pi * 60.0 * np.arange(length) / SAMPLE_RATE) * np.exp(
        -np.arange(length) / (0.03 * SAMPLE_RATE)
    )
    sfx[i0 : i0 + length, 0] += thump * 0.35
    sfx[i0 : i0 + length, 1] += thump * 0.5
    i0, length = int(3.05 * SAMPLE_RATE), int(0.06 * SAMPLE_RATE)
    chirp = np.sin(2.0 * np.pi * (880.0 + 440.0 * np.arange(length) / length) * np.arange(length) / SAMPLE_RATE)
    chirp *= np.minimum(1.0, np.arange(length) / (0.005 * SAMPLE_RATE)) * np.minimum(
        1.0, np.arange(length)[::-1] / (0.005 * SAMPLE_RATE)
    )
    sfx[i0 : i0 + length, 0] += chirp * 0.20
    sfx[i0 : i0 + length, 1] += chirp * 0.47
    vocal_stereo = _center(vocal).astype(np.float32)
    music = score
    sfx_stereo = sfx.astype(np.float32)
    mix = (vocal_stereo.astype(np.float64) + music.astype(np.float64) + sfx_stereo.astype(np.float64)).astype(
        np.float32
    )
    return Clip(
        name="game", sample_rate=SAMPLE_RATE, mix=mix, vocal=vocal_stereo, music=music, sfx=sfx_stereo
    )


def make_crowd_clip(duration_s: float = 3.0, seed: int = 77) -> Clip:
    """Diffuse crowd/choir wash. Glossary Music: suppress, never Vocal."""
    rng = np.random.default_rng(seed)
    frames = int(duration_s * SAMPLE_RATE)
    t = np.arange(frames, dtype=np.float64) / float(SAMPLE_RATE)
    out = np.zeros((frames, NUM_CHANNELS), dtype=np.float64)
    for ch in range(NUM_CHANNELS):
        acc = np.zeros(frames, dtype=np.float64)
        for _ in range(24):
            f = float(rng.uniform(180.0, 600.0))
            phase = rng.uniform(0.0, 2.0 * np.pi)
            am = 0.8 + 0.2 * np.sin(2.0 * np.pi * rng.uniform(0.3, 0.9) * t + phase)
            acc += np.sin(2.0 * np.pi * f * t + phase) * am
        acc /= 24.0
        wash = np.convolve(rng.standard_normal(frames), np.ones(64) / 64.0, mode="same") * 0.4
        mono = acc + wash
        out[:, ch] = mono / (float(np.sqrt(np.mean(mono**2))) + 1e-9) * 0.4
    stereo = out.astype(np.float32)
    return Clip(
        name="crowd",
        sample_rate=SAMPLE_RATE,
        mix=stereo,
        vocal=np.zeros_like(stereo),
        music=stereo,
    )


def make_unison_clip(duration_s: float = 3.0) -> Clip:
    """Ambiguous unison: Vocal and Music share 440Hz; Vocal carries vibrato
    plus syllable motion while Music is sustained. Fail-open keeps Vocal."""
    frames = int(duration_s * SAMPLE_RATE)
    t = np.arange(frames, dtype=np.float64) / float(SAMPLE_RATE)
    vibrato = 1.0 + 0.02 * np.sin(2.0 * np.pi * 5.5 * t)
    am = 0.65 + 0.35 * np.sin(2.0 * np.pi * 4.0 * t) ** 2
    phase_v = 2.0 * np.pi * np.cumsum(440.0 * vibrato) / float(SAMPLE_RATE)
    vocal = (np.sin(phase_v) + 0.5 * np.sin(2.0 * phase_v) + 0.33 * np.sin(3.0 * phase_v)) * am
    music = np.sin(2.0 * np.pi * 440.0 * t) + 0.5 * np.sin(2.0 * np.pi * 442.0 * t)
    vocal *= 0.4 / (float(np.sqrt(np.mean(vocal**2))) + 1e-9)
    music *= 0.4 / (float(np.sqrt(np.mean(music**2))) + 1e-9)
    vocal_stereo = _center(vocal).astype(np.float32)
    music_stereo = _center(music).astype(np.float32)
    return Clip(
        name="unison",
        sample_rate=SAMPLE_RATE,
        mix=(vocal_stereo.astype(np.float64) + music_stereo.astype(np.float64)).astype(np.float32),
        vocal=vocal_stereo,
        music=music_stereo,
    )


def run_clip(
    engine: SilencioEngine,
    clip: Clip,
    block_frames: int = 1024,
    stem: StemName = "mix",
) -> tuple[Float32Stereo, Float32Stereo]:
    """Feed one stem block-by-block through the engine seam and return the
    latency-trimmed steady-state pair ``(output, reference)``.

    The first second (detector convergence plus pipeline priming) and the
    final 0.1s (overlap edge) are excluded: acceptance judges continuous
    live behavior, which is steady-state by nature. The caller owns the
    toggle state; ticket 02 acceptance runs with the toggle ON.
    """
    if stem == "mix":
        source = clip.mix
    elif stem == "vocal":
        source = clip.vocal
    elif stem == "music":
        source = clip.music
    elif stem == "sfx":
        if clip.sfx is None:
            raise ValueError(f"clip {clip.name!r} carries no SFX stem")
        source = clip.sfx
    else:
        raise ValueError(f"unknown stem {stem!r}")
    if source.shape[0] <= _SETTLE_SAMPLES + _TAIL_SAMPLES + LATENCY_SAMPLES:
        raise ValueError(f"clip {clip.name!r} is too short for steady-state metrics")
    blocks: list[Float32Stereo] = []
    for start in range(0, source.shape[0], block_frames):
        blocks.append(engine.process_block(source[start : start + block_frames]))
    # Push the pipeline tail through the seam with zero blocks.
    tail_blocks = (LATENCY_SAMPLES + block_frames - 1) // block_frames
    zero = np.zeros((block_frames, NUM_CHANNELS), dtype=np.float32)
    for _ in range(tail_blocks):
        blocks.append(engine.process_block(zero))
    full = np.concatenate(blocks, axis=0)
    # Output sample k carries input sample k - LATENCY_SAMPLES.
    out = full[LATENCY_SAMPLES : LATENCY_SAMPLES + source.shape[0]]
    assert out.shape == source.shape
    lo = _SETTLE_SAMPLES
    hi = source.shape[0] - _TAIL_SAMPLES
    return out[lo:hi].copy(), source[lo:hi].copy()
