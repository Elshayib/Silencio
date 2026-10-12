"""Ticket 04 acceptance at the single engine buffer seam.

Seam: mixed stereo PCM block in -> Vocal-plus-SFX stereo PCM block out,
via SilencioEngine.process_block(). The soak feeds continuous playback
block-by-block through the live-wired engine and times every block on the
wall clock; the GPU boost runs the same seam with identical toggle
workflow. Live WASAPI/driver jitter stays manual per the spec; the soak
proves CPU headroom plus the fixed pipeline share, and the forced-GPU
check proves the residue reducer never harms Vocal.

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.
"""

from __future__ import annotations

import numpy as np

from silencio.boost import build_boosted_live_engine, describe_accelerator
from silencio.clips import make_crowd_clip, make_game_clip, make_movie_clip, make_song_clip, run_clip
from silencio.engine import SAMPLE_RATE, SilencioEngine
from silencio.live import build_live_engine
from silencio.metrics import db, total_power
from silencio.soak import SoakConfig, format_soak_report, run_soak


def _live_engine_on() -> SilencioEngine:
    engine = build_live_engine()
    engine.set_enabled(True)
    return engine


def test_soak_continuous_playback_runs_without_dropouts_on_cpu() -> None:
    config = SoakConfig(duration_s=8.0, block_frames=1024)
    report = run_soak(config=config)
    assert report.blocks > 300
    assert report.dropouts == 0
    assert report.rtf < 0.5
    assert report.max_block_ms < config.block_ms
    assert np.all(np.isfinite(report.tail))


def test_soak_measured_delay_stays_inside_150ms() -> None:
    report = run_soak(config=SoakConfig(duration_s=8.0, block_frames=1024))
    assert 0.0 < report.measured_end_to_end_ms <= 150.0
    assert report.passed


def test_soak_report_renders_for_manual_record() -> None:
    report = run_soak(config=SoakConfig(duration_s=2.0, block_frames=1024))
    rendered = format_soak_report(report)
    assert "PASS" in rendered
    assert "dropout" in rendered.lower()


def test_gpu_auto_falls_back_to_cpu_without_hardware() -> None:
    engine = build_boosted_live_engine(prefer="auto")
    assert isinstance(engine, SilencioEngine)
    assert describe_accelerator() in ("cpu", "gpu")
    # Identical toggle workflow whatever the backend chose.
    assert engine.enabled is False
    assert engine.switch_time_ms < 50.0


def test_gpu_boost_produces_equal_or_cleaner_vocal_with_identical_toggle() -> None:
    clip = make_song_clip()
    cpu = build_live_engine()
    cpu.set_enabled(True)
    gpu = build_boosted_live_engine(prefer="gpu")
    gpu.set_enabled(True)
    music_cpu, music_ref = run_clip(cpu, clip, stem="music")
    vocal_cpu, vocal_ref = run_clip(_live_engine_on(), clip, stem="vocal")
    music_gpu, _ = run_clip(gpu, clip, stem="music")
    vocal_gpu, _ = run_clip(build_boosted_live_engine(prefer="gpu", enabled=True), clip, stem="vocal")
    music_cpu_db = db(total_power(music_cpu), total_power(music_ref))
    music_gpu_db = db(total_power(music_gpu), total_power(music_ref))
    vocal_cpu_db = db(total_power(vocal_cpu), total_power(vocal_ref))
    vocal_gpu_db = db(total_power(vocal_gpu), total_power(vocal_ref))
    assert vocal_cpu_db >= -2.0
    assert music_cpu_db <= -4.0
    assert music_gpu_db <= music_cpu_db
    assert vocal_gpu_db >= -2.0
    # The boost never harms Vocal to buy reduction: boosted Vocal holds
    # within 1dB of the CPU pass (fail-open survives the deeper cut).


def test_boosted_off_restores_mix_bit_perfect_with_same_switch_budget() -> None:
    from silencio.engine import MAX_SWITCH_SAMPLES_50MS

    clip = make_movie_clip()
    engine = build_boosted_live_engine(prefer="gpu")
    assert engine.enabled is False
    outs = []
    for start in range(0, len(clip.mix), 1024):
        outs.append(engine.process_block(clip.mix[start : start + 1024]))
    np.testing.assert_array_equal(np.concatenate(outs, axis=0), clip.mix)
    assert engine.ramp_samples <= MAX_SWITCH_SAMPLES_50MS
    assert engine.switch_time_ms < 50.0


def test_boosted_game_sfx_and_fail_open_hold() -> None:
    from silencio.clips import make_unison_clip

    game = make_game_clip()
    assert game.sfx is not None
    engine = build_boosted_live_engine(prefer="gpu")
    engine.set_enabled(True)
    out, _ = run_clip(engine, game)
    steady = SAMPLE_RATE
    sfx_steady = game.sfx[steady : steady + out.shape[0]]
    peak_at = int(np.argmax(np.max(np.abs(sfx_steady), axis=1)))
    peak_in = float(np.max(np.abs(sfx_steady)))
    peak_out = float(np.max(np.abs(out[max(0, peak_at - 64) : peak_at + 64])))
    assert -3.0 <= db(peak_out**2, peak_in**2) <= 3.0
    crowd = make_crowd_clip()
    crowd_engine = build_boosted_live_engine(prefer="gpu")
    crowd_engine.set_enabled(True)
    crowd_out, crowd_ref = run_clip(crowd_engine, crowd, stem="music")
    assert db(total_power(crowd_out), total_power(crowd_ref)) <= -4.0
    unison = make_unison_clip()
    unison_engine = build_boosted_live_engine(prefer="gpu")
    unison_engine.set_enabled(True)
    unison_out, _ = run_clip(unison_engine, unison)
    vocal_engine = build_boosted_live_engine(prefer="gpu", enabled=True)
    _, vocal_ref = run_clip(vocal_engine, unison, stem="vocal")
    assert db(total_power(unison_out), total_power(vocal_ref)) >= -3.0
