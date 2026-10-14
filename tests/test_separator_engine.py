"""Ticket 02 acceptance at the single engine buffer seam.

Seam: mixed stereo PCM block in -> Vocal-plus-SFX stereo PCM block out,
via SilencioEngine.process_block() + set_enabled() with the causal
separator plugged in as the engine processor. Acceptance clips run through
this seam deterministically (no virtual cable or live driver needed).

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.

Thresholds come from the spec, not the implementation: strong Music
reduction is roughly 4dB or more (spec Implementation Decisions), Vocal is
kept intelligible (near unity), ambiguous sound fails open toward Vocal,
and end-to-end delay stays at or under 150ms.
"""

from __future__ import annotations

import time

import numpy as np

from silencio.clips import (
    GAME_BLIP_S,
    GAME_SCORE_GAP_S,
    MOVIE_SCORE_GAP_S,
    make_crowd_clip,
    make_game_clip,
    make_movie_clip,
    make_song_clip,
    make_unison_clip,
    run_clip,
)
from silencio.engine import MAX_SWITCH_SAMPLES_50MS, SAMPLE_RATE, SilencioEngine
from silencio.metrics import bandpower, correlation, db, lr_ratio_db, total_power
from silencio.separator import LATENCY_SAMPLES, CausalSeparator


def _engine_with_separator() -> SilencioEngine:
    engine = SilencioEngine(processor=CausalSeparator())
    engine.set_enabled(True)
    return engine


def test_song_clip_keeps_vocal_with_accompaniment_reduced() -> None:
    clip = make_song_clip()
    out, ref = run_clip(_engine_with_separator(), clip)
    vocal_band_in = bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0)
    vocal_band_out = bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0)
    # Lead singing stays intelligible: Vocal-band level holds near unity.
    assert db(vocal_band_out, vocal_band_in) >= -3.0
    # No pumping: the separator must not make the mix louder either.
    assert db(vocal_band_out, vocal_band_in) <= 1.0
    bass_in = bandpower(ref[:, 0] + ref[:, 1], 40.0, 200.0)
    bass_out = bandpower(out[:, 0] + out[:, 1], 40.0, 200.0)
    # Accompaniment bass drops strongly into the background.
    assert db(bass_out, bass_in) <= -4.0


def test_song_stems_music_reduced_more_than_vocal_touched() -> None:
    clip = make_song_clip()
    music_out, music_ref = run_clip(_engine_with_separator(), clip, stem="music")
    vocal_out, vocal_ref = run_clip(_engine_with_separator(), clip, stem="vocal")
    music_delta = db(float(np.mean(music_out**2)), float(np.mean(music_ref**2)))
    vocal_delta = db(float(np.mean(vocal_out**2)), float(np.mean(vocal_ref**2)))
    assert music_delta <= -4.0
    assert vocal_delta >= -2.0
    # Separation means Music is hurt strictly more than Vocal.
    assert music_delta <= vocal_delta - 2.0


def test_off_passthrough_stays_bit_perfect_with_separator_plugged() -> None:
    clip = make_song_clip()
    engine = SilencioEngine(processor=CausalSeparator())
    assert engine.enabled is False
    outs = []
    for start in range(0, len(clip.mix), 1024):
        outs.append(engine.process_block(clip.mix[start : start + 1024]))
    np.testing.assert_array_equal(np.concatenate(outs, axis=0), clip.mix)


def test_output_block_chunking_is_deterministic() -> None:
    # Pure streaming state: identical chunkings give identical output, so
    # live block sizes never change what the listener hears.
    clip = make_song_clip()
    first = run_clip(_engine_with_separator(), clip, block_frames=256)[0]
    second = run_clip(_engine_with_separator(), clip, block_frames=2048)[0]
    assert first.shape == second.shape
    np.testing.assert_array_equal(first, second)


def test_separator_latency_fits_live_budget() -> None:
    assert LATENCY_SAMPLES == CausalSeparator().latency_samples
    assert LATENCY_SAMPLES <= int(0.150 * SAMPLE_RATE)
    assert CausalSeparator().sample_rate == 48000
    assert CausalSeparator().num_channels == 2


def test_toggle_switch_budget_holds_with_separator() -> None:
    engine = SilencioEngine(processor=CausalSeparator())
    engine.set_enabled(True)
    assert engine.ramp_samples <= MAX_SWITCH_SAMPLES_50MS


def test_device_change_resets_separator_without_restart() -> None:
    engine = SilencioEngine(processor=CausalSeparator())
    engine.set_enabled(True)
    clip = make_song_clip()
    engine.process_block(clip.mix[:2048])
    engine.reset_for_device_change()
    assert engine.enabled is True
    out = engine.process_block(np.zeros((1024, 2), dtype=np.float32))
    assert out.shape == (1024, 2)
    assert np.all(np.isfinite(out))


def test_movie_dialogue_kept_score_reduced() -> None:
    clip = make_movie_clip()
    out, ref = run_clip(_engine_with_separator(), clip)
    vocal_band_in = bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0)
    vocal_band_out = bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0)
    # Dialogue stays clear: Vocal band holds near unity in the mix.
    assert db(vocal_band_out, vocal_band_in) >= -2.0
    music_out, music_ref = run_clip(_engine_with_separator(), clip, stem="music")
    vocal_out, vocal_ref = run_clip(_engine_with_separator(), clip, stem="vocal")
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    assert vocal_delta >= -2.0
    assert music_delta <= -4.0
    assert music_delta <= vocal_delta - 2.0
    # Where dialogue drops out, the exposed score has faded far back.
    gap_start = int(MOVIE_SCORE_GAP_S[0] * SAMPLE_RATE) - SAMPLE_RATE
    gap_end = int(MOVIE_SCORE_GAP_S[1] * SAMPLE_RATE) - SAMPLE_RATE
    assert db(total_power(out[gap_start:gap_end]), total_power(ref[gap_start:gap_end])) <= -4.0


def test_game_dialogue_and_sfx_kept_score_reduced() -> None:
    clip = make_game_clip()
    out, ref = run_clip(_engine_with_separator(), clip)
    vocal_band_in = bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0)
    vocal_band_out = bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0)
    assert db(vocal_band_out, vocal_band_in) >= -2.0
    music_out, music_ref = run_clip(_engine_with_separator(), clip, stem="music")
    vocal_out, vocal_ref = run_clip(_engine_with_separator(), clip, stem="vocal")
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    assert vocal_delta >= -2.0
    assert music_delta <= -4.0
    assert music_delta <= vocal_delta - 2.0
    gap_start = int(GAME_SCORE_GAP_S[0] * SAMPLE_RATE) - SAMPLE_RATE
    gap_end = int(GAME_SCORE_GAP_S[1] * SAMPLE_RATE) - SAMPLE_RATE
    assert db(total_power(out[gap_start:gap_end]), total_power(ref[gap_start:gap_end])) <= -4.0


def test_game_sfx_gunshot_peak_preserved() -> None:
    clip = make_game_clip()
    assert clip.sfx is not None
    out, ref = run_clip(_engine_with_separator(), clip)
    steady_offset = SAMPLE_RATE  # run_clip drops the first second
    sfx_steady = clip.sfx[steady_offset : steady_offset + out.shape[0]]
    peak_at = int(np.argmax(np.max(np.abs(sfx_steady), axis=1)))
    peak_in = float(np.max(np.abs(sfx_steady)))
    peak_out = float(np.max(np.abs(out[max(0, peak_at - 64) : peak_at + 64])))
    assert peak_in > 0.1
    # The gunshot transient survives at full crack, without overshoot.
    assert db(peak_out**2, peak_in**2) >= -3.0
    assert db(peak_out**2, peak_in**2) <= 3.0


def test_game_sfx_footstep_thump_preserved() -> None:
    # Bass transient path (60Hz thump): per-bin onset plus scalar bass keep.
    clip = make_game_clip()
    assert clip.sfx is not None
    out, _ = run_clip(_engine_with_separator(), clip)
    steady_offset = SAMPLE_RATE
    start = int(2.30 * SAMPLE_RATE) - steady_offset
    span = int(0.10 * SAMPLE_RATE)
    stem_window = clip.sfx[steady_offset + start : steady_offset + start + span]
    out_window = out[start : start + span]
    peak_in = float(np.max(np.abs(stem_window)))
    peak_out = float(np.max(np.abs(out_window)))
    assert peak_in > 0.1
    assert db(peak_out**2, peak_in**2) >= -3.0
    assert db(peak_out**2, peak_in**2) <= 3.0


def test_game_sfx_stereo_imaging_preserved() -> None:
    clip = make_game_clip()
    assert clip.sfx is not None
    out, _ = run_clip(_engine_with_separator(), clip)
    steady_offset = SAMPLE_RATE
    # Judge imaging where the SFX dominates: around the blip peak.
    blip_start = int(GAME_BLIP_S * SAMPLE_RATE)
    blip_span = int(0.06 * SAMPLE_RATE)
    blip_region = clip.sfx[blip_start : blip_start + blip_span]
    peak_in_region = int(np.argmax(np.max(np.abs(blip_region), axis=1)))
    peak_at = (blip_start + peak_in_region) - steady_offset
    window = 128
    stem_window = clip.sfx[steady_offset + peak_at - window : steady_offset + peak_at + window]
    out_window = out[peak_at - window : peak_at + window]
    stem_lr = lr_ratio_db(stem_window)
    out_lr = lr_ratio_db(out_window)
    # Direction survives: same dominant side as the UI blip stem ...
    assert np.sign(out_lr) == np.sign(stem_lr)
    # ... with the pan ratio close (residue pulls it slightly center).
    assert abs(out_lr - stem_lr) <= 2.5


def test_game_blip_waveform_dominates_output() -> None:
    clip = make_game_clip()
    assert clip.sfx is not None
    out, _ = run_clip(_engine_with_separator(), clip)
    steady_offset = SAMPLE_RATE
    start = int(GAME_BLIP_S * SAMPLE_RATE) - steady_offset
    span = int(0.06 * SAMPLE_RATE)
    out_window = out[start : start + span]
    stem_window = clip.sfx[steady_offset + start : steady_offset + start + span]
    assert correlation(out_window, stem_window) >= 0.7


def test_crowd_and_choir_treated_as_music() -> None:
    # Stadium wash and backing oohs are Music per the glossary: they must
    # drop far into the background, never leak through as Vocal.
    clip = make_crowd_clip()
    out, ref = run_clip(_engine_with_separator(), clip, stem="music")
    assert db(total_power(out), total_power(ref)) <= -4.0


def test_ambiguous_unison_fails_open_toward_vocal() -> None:
    # Vocal and Music sharing one pitch is genuinely ambiguous: the worst
    # case favors keeping Vocal, leaking Music instead of clipping speech.
    clip = make_unison_clip()
    out, _ = run_clip(_engine_with_separator(), clip)
    _, vocal_ref = run_clip(_engine_with_separator(), clip, stem="vocal")
    assert vocal_ref.shape == out.shape
    assert db(total_power(out), total_power(vocal_ref)) >= -3.0


def test_separator_runs_faster_than_realtime_on_cpu() -> None:
    clip = make_game_clip()
    engine = _engine_with_separator()
    started = time.perf_counter()
    run_clip(engine, clip)
    elapsed = time.perf_counter() - started
    audio_seconds = float(clip.mix.shape[0] - SAMPLE_RATE) / float(SAMPLE_RATE)
    assert elapsed < 0.5 * audio_seconds


def test_separator_output_has_no_clicks() -> None:
    clip = make_song_clip()
    out, ref = run_clip(_engine_with_separator(), clip)
    assert np.all(np.isfinite(out))
    in_step = float(np.max(np.abs(np.diff(ref.astype(np.float64), axis=0))))
    out_step = float(np.max(np.abs(np.diff(out.astype(np.float64), axis=0))))
    # No sample-to-sample jump may exceed the mix's own steepest slope by
    # more than a small factor (an unramped switch would jump ~0.5).
    assert out_step <= 3.0 * in_step + 1e-6
    assert out_step < 0.3


def test_clip_rates_follow_the_engine_seam() -> None:
    for clip in (make_song_clip(), make_movie_clip(), make_game_clip(), make_crowd_clip(), make_unison_clip()):
        assert clip.sample_rate == SAMPLE_RATE
        assert clip.mix.shape[1] == 2
        assert clip.mix.dtype == np.float32


def test_harness_reports_full_acceptance() -> None:
    from silencio.harness import format_report, run_acceptance

    report = run_acceptance()
    assert len(report.checks) >= 10
    assert report.passed
    rendered = format_report(report)
    assert "FAIL" not in rendered
def test_cold_start_mid_playback_has_no_amplified_window_edge():
    from silencio.clips import make_song_clip
    from silencio.separator import CausalSeparator
    source = make_song_clip().mix[2048:2048+4096] * .2
    processor = CausalSeparator()
    output = np.concatenate([processor(source[i:i+128]) for i in range(0,len(source),128)])
    assert np.max(np.abs(np.diff(output,axis=0))) < .06
    assert np.max(np.abs(output)) < 1
