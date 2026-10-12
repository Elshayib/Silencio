"""Continuous CPU soak plus measured delay (ticket 04).

Thin harness around the single engine buffer seam: mixed stereo PCM
blocks in, Vocal-plus-SFX stereo PCM blocks out. It feeds gapless
continuous playback block-by-block through the live-wired engine and
times every block on the wall clock, so the ticket 04 checklist
(no dropouts on CPU alone, measured delay inside budget) is proven at
the same seam the acceptance clips use — no virtual cable or live
driver needed.

A dropout is a block whose wall-clock processing time exceeds its
audio duration: on a live graph that block would glitch. The measured
end-to-end delay is the ticket 03 static estimate (capture plus render
double-buffering plus separator pipeline plus toggle ramp) plus the
observed p95 block processing time, so driver/hardware jitter stays
the only manual part (per the spec, virtual devices are flaky under
automation).

Source material is the deterministic ticket 02 acceptance mixes tiled
gaplessly to the requested duration; mid-soak toggle flips exercise
the gapless switch under load.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from silencio.engine import SAMPLE_RATE, SilencioEngine
from silencio.live import build_live_engine, estimate_end_to_end_ms

Float32Stereo = NDArray[np.float32]


@dataclass(frozen=True)
class SoakConfig:
    """Soak length and live block size."""

    duration_s: float = 30.0
    block_frames: int = 1024
    ramp_samples: int = 480
    toggles: int = 2

    @property
    def block_ms(self) -> float:
        return float(self.block_frames) / float(SAMPLE_RATE) * 1000.0


@dataclass(frozen=True)
class SoakReport:
    """Measured outcome of one continuous soak run."""

    blocks: int
    dropouts: int
    mean_block_ms: float
    p95_block_ms: float
    max_block_ms: float
    rtf: float
    measured_end_to_end_ms: float
    passed: bool
    tail: Float32Stereo


def _continuous_source(frames: int) -> Float32Stereo:
    """Tile the deterministic acceptance mixes gaplessly to ``frames``."""
    from silencio.clips import make_game_clip, make_movie_clip, make_song_clip

    loop = np.concatenate(
        [make_song_clip().mix, make_movie_clip().mix, make_game_clip().mix], axis=0
    )
    repeats = frames // int(loop.shape[0]) + 1
    tiled = np.tile(loop, (repeats, 1))[:frames]
    return np.ascontiguousarray(tiled, dtype=np.float32)


def run_soak(
    engine_factory: Callable[[], SilencioEngine] | None = None,
    config: SoakConfig | None = None,
) -> SoakReport:
    """Run continuous playback and time every block on the wall clock."""
    import time

    cfg = config if config is not None else SoakConfig()
    if cfg.duration_s <= 0.0:
        raise ValueError(f"duration_s must be positive, got {cfg.duration_s}")
    if cfg.block_frames <= 0:
        raise ValueError(f"block_frames must be positive, got {cfg.block_frames}")

    frames = int(cfg.duration_s * SAMPLE_RATE)
    source = _continuous_source(frames)

    def _default_factory() -> SilencioEngine:
        engine = build_live_engine(ramp_samples=cfg.ramp_samples)
        engine.set_enabled(True)
        return engine

    factory = engine_factory if engine_factory is not None else _default_factory
    engine = factory()

    # Warm-up (untimed): cold-start allocation plus detector convergence
    # are priming, not continuous-playback behavior — the live stream
    # primes on start, and ticket 02 metrics likewise exclude the first
    # second. One second of source audio, untimed.
    warmup = source[: min(frames, SAMPLE_RATE)]
    for start in range(0, warmup.shape[0], cfg.block_frames):
        engine.process_block(warmup[start : start + cfg.block_frames])

    toggle_at: set[int] = set()
    if cfg.toggles > 0:
        for k in range(1, cfg.toggles + 1):
            toggle_at.add(int(k * frames / (cfg.toggles + 1) // cfg.block_frames))

    block_times_ms: list[float] = []
    dropouts = 0
    total_wall = 0.0
    last_out: Float32Stereo = np.zeros((cfg.block_frames, 2), dtype=np.float32)
    n_blocks = 0
    for index, start in enumerate(range(0, frames, cfg.block_frames)):
        if index in toggle_at:
            engine.set_enabled(not engine.enabled)
        block = source[start : start + cfg.block_frames]
        started = time.perf_counter()
        out = engine.process_block(block)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        total_wall += elapsed_ms / 1000.0
        block_times_ms.append(elapsed_ms)
        if elapsed_ms > cfg.block_ms:
            dropouts += 1
        if not np.all(np.isfinite(out)):
            dropouts += 1
        last_out = np.asarray(out, dtype=np.float32)
        n_blocks += 1
    # Leave the engine ON for the next run; the soak owns its instance.
    if not engine.enabled:
        engine.set_enabled(True)

    audio_seconds = float(frames) / float(SAMPLE_RATE)
    ordered = sorted(block_times_ms)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    mean_ms = float(sum(block_times_ms) / max(1, len(block_times_ms)))
    max_ms = float(ordered[-1]) if ordered else 0.0
    measured = estimate_end_to_end_ms(
        block_frames=cfg.block_frames, ramp_samples=engine.ramp_samples
    ) + p95
    rtf = total_wall / audio_seconds if audio_seconds > 0 else 0.0
    passed = bool(dropouts == 0 and measured <= 150.0 and rtf < 0.5)
    return SoakReport(
        blocks=n_blocks,
        dropouts=dropouts,
        mean_block_ms=mean_ms,
        p95_block_ms=float(p95),
        max_block_ms=max_ms,
        rtf=float(rtf),
        measured_end_to_end_ms=float(measured),
        passed=passed,
        tail=last_out,
    )


def format_soak_report(report: SoakReport) -> str:
    """Render the soak outcome for the terminal / live-AB record."""
    mark = "PASS" if report.passed else "FAIL"
    return (
        f"Silencio ticket 04 soak [{mark}]: "
        f"{report.blocks} blocks, {report.dropouts} dropouts, "
        f"RTF {report.rtf:.2f}, mean {report.mean_block_ms:.2f}ms "
        f"p95 {report.p95_block_ms:.2f}ms max {report.max_block_ms:.2f}ms, "
        f"measured end-to-end {report.measured_end_to_end_ms:.1f}ms "
        "(budget 150ms)"
    )
