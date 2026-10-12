"""Offline acceptance harness for ticket 02 (no audio hardware needed).

Runs the three fixed clips plus the crowd and unison probes through the
engine buffer seam and reports Vocal-kept / Music-reduced / SFX-kept
numbers. Thresholds repeat the spec criteria (strong Music reduction is
roughly 4dB or more; Vocal holds near unity; ambiguous sound fails open
toward Vocal); they are stated literally here so the printed record can
be judged without reading the test suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from silencio.clips import (
    GAME_BLIP_S,
    GAME_SCORE_GAP_S,
    MOVIE_SCORE_GAP_S,
    Clip,
    make_crowd_clip,
    make_game_clip,
    make_movie_clip,
    make_song_clip,
    make_unison_clip,
    run_clip,
)
from silencio.engine import SAMPLE_RATE, SilencioEngine
from silencio.metrics import bandpower, correlation, db, lr_ratio_db, total_power
from silencio.separator import LATENCY_SAMPLES, CausalSeparator


@dataclass(frozen=True)
class Check:
    name: str
    detail: str
    passed: bool


@dataclass(frozen=True)
class AcceptanceReport:
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _on_engine() -> SilencioEngine:
    engine = SilencioEngine(processor=CausalSeparator())
    engine.set_enabled(True)
    return engine


def _gap_db(clip: Clip, gap_s: tuple[float, float], block_frames: int) -> tuple[float, str]:
    out, ref = run_clip(_on_engine(), clip, block_frames=block_frames)
    lo = int(gap_s[0] * SAMPLE_RATE) - SAMPLE_RATE
    hi = int(gap_s[1] * SAMPLE_RATE) - SAMPLE_RATE
    delta = db(total_power(out[lo:hi]), total_power(ref[lo:hi]))
    return delta, f"{delta:+.1f}dB exposed-score in gap"


def run_acceptance(block_frames: int = 1024) -> AcceptanceReport:
    """Run every ticket 02 acceptance check through the buffer seam."""
    checks: list[Check] = []

    song = make_song_clip()
    out, ref = run_clip(_on_engine(), song, block_frames=block_frames)
    vb = db(
        bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0),
        bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0),
    )
    bass = db(
        bandpower(out[:, 0] + out[:, 1], 40.0, 200.0),
        bandpower(ref[:, 0] + ref[:, 1], 40.0, 200.0),
    )
    music_out, music_ref = run_clip(_on_engine(), song, block_frames=block_frames, stem="music")
    vocal_out, vocal_ref = run_clip(_on_engine(), song, block_frames=block_frames, stem="vocal")
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    checks.append(Check("song Vocal kept", f"Vocal band {vb:+.1f}dB", vb >= -3.0))
    checks.append(Check("song Music bass reduced", f"bass {bass:+.1f}dB", bass <= -4.0))
    checks.append(
        Check(
            "song Music reduced more than Vocal touched",
            f"Music {music_delta:+.1f}dB vs Vocal {vocal_delta:+.1f}dB",
            music_delta <= -4.0 and vocal_delta >= -2.0 and music_delta <= vocal_delta - 2.0,
        )
    )

    for clip, gap in ((make_movie_clip(), MOVIE_SCORE_GAP_S), (make_game_clip(), GAME_SCORE_GAP_S)):
        out, ref = run_clip(_on_engine(), clip, block_frames=block_frames)
        vb = db(
            bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0),
            bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0),
        )
        music_out, music_ref = run_clip(_on_engine(), clip, block_frames=block_frames, stem="music")
        vocal_out, vocal_ref = run_clip(_on_engine(), clip, block_frames=block_frames, stem="vocal")
        music_delta = db(total_power(music_out), total_power(music_ref))
        vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
        gap_delta, gap_detail = _gap_db(clip, gap, block_frames)
        checks.append(Check(f"{clip.name} dialogue kept", f"Vocal band {vb:+.1f}dB", vb >= -2.0))
        checks.append(
            Check(
                f"{clip.name} score reduced",
                f"Music {music_delta:+.1f}dB vs Vocal {vocal_delta:+.1f}dB; gap {gap_detail}",
                vocal_delta >= -2.0 and music_delta <= -4.0 and gap_delta <= -4.0,
            )
        )

    game = make_game_clip()
    assert game.sfx is not None
    out, _ = run_clip(_on_engine(), game, block_frames=block_frames)
    sfx_steady = game.sfx[SAMPLE_RATE : SAMPLE_RATE + out.shape[0]]
    peak_at = int(np.argmax(np.max(np.abs(sfx_steady), axis=1)))
    peak_in = float(np.max(np.abs(sfx_steady)))
    peak_out = float(np.max(np.abs(out[max(0, peak_at - 64) : peak_at + 64])))
    peak_delta = db(peak_out**2, peak_in**2)
    blip_start = int(GAME_BLIP_S * SAMPLE_RATE)
    blip_region = game.sfx[blip_start : blip_start + int(0.06 * SAMPLE_RATE)]
    blip_peak = blip_start + int(np.argmax(np.max(np.abs(blip_region), axis=1))) - SAMPLE_RATE
    stem_window = game.sfx[SAMPLE_RATE + blip_peak - 128 : SAMPLE_RATE + blip_peak + 128]
    out_window = out[blip_peak - 128 : blip_peak + 128]
    stem_lr = lr_ratio_db(stem_window)
    out_lr = lr_ratio_db(out_window)
    span = int(0.06 * SAMPLE_RATE)
    onset_at = int(GAME_BLIP_S * SAMPLE_RATE) - SAMPLE_RATE
    corr_full = correlation(
        out[onset_at : onset_at + span],
        game.sfx[SAMPLE_RATE + onset_at : SAMPLE_RATE + onset_at + span],
    )
    checks.append(
        Check("game SFX transients kept", f"gunshot peak {peak_delta:+.1f}dB", -3.0 <= peak_delta <= 3.0)
    )
    checks.append(
        Check(
            "game SFX imaging kept",
            f"blip L/R stem {stem_lr:+.1f}dB vs out {out_lr:+.1f}dB; corr {corr_full:.2f}",
            np.sign(out_lr) == np.sign(stem_lr)
            and abs(out_lr - stem_lr) <= 2.5
            and corr_full >= 0.7,
        )
    )

    crowd = make_crowd_clip()
    crowd_out, crowd_ref = run_clip(_on_engine(), crowd, block_frames=block_frames, stem="music")
    crowd_delta = db(total_power(crowd_out), total_power(crowd_ref))
    checks.append(
        Check("crowd/choir treated as Music", f"crowd {crowd_delta:+.1f}dB", crowd_delta <= -4.0)
    )

    unison = make_unison_clip()
    unison_out, _ = run_clip(_on_engine(), unison, block_frames=block_frames)
    _, unison_vocal = run_clip(_on_engine(), unison, block_frames=block_frames, stem="vocal")
    unison_delta = db(total_power(unison_out), total_power(unison_vocal))
    checks.append(
        Check(
            "ambiguous unison fails open toward Vocal",
            f"mix out vs Vocal {unison_delta:+.1f}dB",
            unison_delta >= -3.0,
        )
    )

    off_engine = SilencioEngine(processor=CausalSeparator())
    off_out: list[np.ndarray] = []
    for start in range(0, song.mix.shape[0], block_frames):
        off_out.append(off_engine.process_block(song.mix[start : start + block_frames]))
    bit_perfect = bool(np.array_equal(np.concatenate(off_out, axis=0), song.mix))
    checks.append(Check("toggle OFF bit-perfect", "mix untouched", bit_perfect))

    first = run_clip(_on_engine(), song, block_frames=256)[0]
    second = run_clip(_on_engine(), song, block_frames=2048)[0]
    checks.append(
        Check(
            "streaming deterministic across block sizes",
            f"max diff {float(np.max(np.abs(first - second))):.1e}",
            bool(np.array_equal(first, second)),
        )
    )

    latency_ms = LATENCY_SAMPLES / SAMPLE_RATE * 1000.0
    checks.append(
        Check(
            "latency inside live budget",
            f"{LATENCY_SAMPLES} samples = {latency_ms:.1f}ms (budget 150ms)",
            LATENCY_SAMPLES <= int(0.150 * SAMPLE_RATE),
        )
    )

    started = time.perf_counter()
    run_clip(_on_engine(), game, block_frames=block_frames)
    elapsed = time.perf_counter() - started
    audio_seconds = float(game.mix.shape[0] - SAMPLE_RATE) / float(SAMPLE_RATE)
    checks.append(
        Check(
            "CPU faster than realtime",
            f"RTF {elapsed / audio_seconds:.2f}",
            elapsed < 0.5 * audio_seconds,
        )
    )

    return AcceptanceReport(checks=tuple(checks))


def format_report(report: AcceptanceReport) -> str:
    """Render the report for the terminal / live-AB record."""
    lines = ["Silencio ticket 02 acceptance (buffer seam, no hardware)"]
    for check in report.checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    lines.append("Manual live AB still required: browser/movie/game audible,")
    lines.append("mid-sound toggle gapless, headphone replug recovers.")
    return "\n".join(lines)
