"""Ticket 03 acceptance at the single engine buffer seam.

Seam: mixed stereo PCM block in -> Vocal-plus-SFX stereo PCM block out,
via the live-wired engine (``build_live_engine``) through
``SilencioEngine.process_block``. Live WASAPI/tray/hotkey/device-driver
behaviour stays manual per the spec; resampling, latency, and
output-only guards are thin adapters around the same seam.

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.
"""

from __future__ import annotations

import numpy as np

from silencio.clips import (
    GAME_SCORE_GAP_S,
    MOVIE_SCORE_GAP_S,
    make_game_clip,
    make_movie_clip,
    make_song_clip,
    run_clip,
)
from silencio.engine import SAMPLE_RATE
from silencio.live import (
    build_live_engine,
    ensure_output_only_input,
    estimate_end_to_end_ms,
    resample_source_to_pipeline,
)
from silencio.metrics import bandpower, correlation, db, lr_ratio_db, total_power


def test_live_engine_off_restores_mix_bit_perfect() -> None:
    clip = make_song_clip()
    engine = build_live_engine()
    assert engine.enabled is False
    outs = []
    for start in range(0, len(clip.mix), 1024):
        outs.append(engine.process_block(clip.mix[start : start + 1024]))
    np.testing.assert_array_equal(np.concatenate(outs, axis=0), clip.mix)


def test_live_engine_on_keeps_vocal_and_reduces_music() -> None:
    clip = make_song_clip()
    engine = build_live_engine()
    engine.set_enabled(True)
    music_out, music_ref = run_clip(engine, clip, stem="music")
    vocal_out, vocal_ref = run_clip(engine, clip, stem="vocal")
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    assert vocal_delta >= -2.0
    assert music_delta <= -4.0
    assert music_delta <= vocal_delta - 2.0


def test_live_browser_movie_game_song_sources_all_filter_when_on() -> None:
    # Any playback source routes through the same live seam. The acceptance
    # corpus defines three fixed clips; browser/YouTube tabs carry
    # dialogue over score exactly like the movie path (speech over a wide
    # sustained bed through the same loopback), so the movie clip stands in
    # for them here and the full four-source AB stays manual (ticket 06).
    for clip, gap in (
        (make_movie_clip(), MOVIE_SCORE_GAP_S),
        (make_game_clip(), GAME_SCORE_GAP_S),
    ):
        engine = build_live_engine()
        engine.set_enabled(True)
        out, ref = run_clip(engine, clip)
        vocal_band = db(
            bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0),
            bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0),
        )
        assert vocal_band >= -2.0
        gap_lo = int(gap[0] * SAMPLE_RATE) - SAMPLE_RATE
        gap_hi = int(gap[1] * SAMPLE_RATE) - SAMPLE_RATE
        assert db(total_power(out[gap_lo:gap_hi]), total_power(ref[gap_lo:gap_hi])) <= -4.0
    song = make_song_clip()
    engine = build_live_engine()
    engine.set_enabled(True)
    out, ref = run_clip(engine, song)
    assert db(total_power(out), total_power(ref)) < 0.0


def test_live_off_restores_every_source_bit_perfect() -> None:
    for clip in (make_song_clip(), make_movie_clip(), make_game_clip()):
        engine = build_live_engine()
        assert engine.enabled is False
        outs = []
        for start in range(0, len(clip.mix), 1024):
            outs.append(engine.process_block(clip.mix[start : start + 1024]))
        np.testing.assert_array_equal(np.concatenate(outs, axis=0), clip.mix)


def test_live_teammate_speech_over_speakers_preserved_as_vocal() -> None:
    # Teammate speech arrives over speakers as Vocal dialogue: the live
    # engine keeps the Vocal stem near unity while suppressing the score.
    clip = make_game_clip()
    engine = build_live_engine()
    engine.set_enabled(True)
    vocal_out, vocal_ref = run_clip(engine, clip, stem="vocal")
    music_out, music_ref = run_clip(engine, clip, stem="music")
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    music_delta = db(total_power(music_out), total_power(music_ref))
    assert vocal_delta >= -2.0
    assert music_delta <= vocal_delta - 2.0


def test_live_crowd_and_choir_stay_music_through_live_engine() -> None:
    # Crowd/choir pads are Music per the glossary even on the live path:
    # the same separator behind the live seam must push them far back.
    from silencio.clips import make_crowd_clip

    clip = make_crowd_clip()
    engine = build_live_engine()
    engine.set_enabled(True)
    out, ref = run_clip(engine, clip, stem="music")
    assert db(total_power(out), total_power(ref)) <= -4.0


def test_live_toggle_mid_sound_stays_gapless_with_separator() -> None:
    # Gapless with the real separator plugged in: flipping ON mid-song
    # crossfades between mixes that differ a lot, yet no sample step may
    # resemble a pop/click.
    clip = make_song_clip()
    engine = build_live_engine()
    steady = np.concatenate(
        [engine.process_block(clip.mix[i : i + 512]) for i in range(0, 2048, 512)], axis=0
    )
    natural = float(np.max(np.abs(np.diff(steady.astype(np.float64), axis=0))))
    engine.set_enabled(True)
    outputs = [engine.process_block(clip.mix[i : i + 128]) for i in range(2048, 2048 + 960, 128)]
    stream = np.concatenate(outputs, axis=0)
    step = float(np.max(np.abs(np.diff(stream.astype(np.float64), axis=0))))
    assert step <= 3.0 * natural + 1e-6
    assert step < 0.3
    assert engine.switch_time_ms < 50.0


def test_live_ambiguous_unison_still_fails_open_through_live_engine() -> None:
    from silencio.clips import make_unison_clip

    clip = make_unison_clip()
    engine = build_live_engine()
    engine.set_enabled(True)
    out, _ = run_clip(engine, clip)
    vocal_engine = build_live_engine()
    vocal_engine.set_enabled(True)
    _, vocal_ref = run_clip(vocal_engine, clip, stem="vocal")
    assert db(total_power(out), total_power(vocal_ref)) >= -3.0


def test_live_game_sfx_kept_with_imaging_through_live_engine() -> None:
    # SFX travel the live path untouched alongside Vocal: gunshot peak
    # holds and the UI blip keeps its stereo pan.
    from silencio.clips import GAME_BLIP_S

    clip = make_game_clip()
    assert clip.sfx is not None
    engine = build_live_engine()
    engine.set_enabled(True)
    out, _ = run_clip(engine, clip)
    steady = SAMPLE_RATE
    sfx_steady = clip.sfx[steady : steady + out.shape[0]]
    peak_at = int(np.argmax(np.max(np.abs(sfx_steady), axis=1)))
    peak_in = float(np.max(np.abs(sfx_steady)))
    peak_out = float(np.max(np.abs(out[max(0, peak_at - 64) : peak_at + 64])))
    assert -3.0 <= db(peak_out**2, peak_in**2) <= 3.0
    blip_start = int(GAME_BLIP_S * SAMPLE_RATE)
    blip_span = int(0.06 * SAMPLE_RATE)
    region = clip.sfx[blip_start : blip_start + blip_span]
    peak_in_region = int(np.argmax(np.max(np.abs(region), axis=1)))
    peak_fr = (blip_start + peak_in_region) - steady
    stem_window = clip.sfx[steady + peak_fr - 128 : steady + peak_fr + 128]
    out_window = out[peak_fr - 128 : peak_fr + 128]
    assert np.sign(lr_ratio_db(out_window)) == np.sign(lr_ratio_db(stem_window))
    assert abs(lr_ratio_db(out_window) - lr_ratio_db(stem_window)) <= 2.5
    onset = int(GAME_BLIP_S * SAMPLE_RATE) - steady
    span = int(0.06 * SAMPLE_RATE)
    assert correlation(out[onset : onset + span], clip.sfx[steady + onset : steady + onset + span]) >= 0.7


def test_live_on_never_boosts_loudness_parity() -> None:
    # Loudness parity: ON removes Music so the mix never gets louder than
    # OFF; the Vocal path itself holds unity gain (no auto-makeup).
    clip = make_song_clip()
    engine = build_live_engine()
    engine.set_enabled(True)
    out, ref = run_clip(engine, clip)
    assert db(total_power(out), total_power(ref)) <= 1.0
    vocal_engine = build_live_engine()
    vocal_engine.set_enabled(True)
    vocal_out, vocal_ref = run_clip(vocal_engine, clip, stem="vocal")
    assert db(total_power(vocal_out), total_power(vocal_ref)) >= -2.0
    assert db(total_power(vocal_out), total_power(vocal_ref)) <= 1.0


def test_live_end_to_end_latency_stays_inside_150ms() -> None:
    ms = estimate_end_to_end_ms(block_frames=1024, ramp_samples=480)
    assert 0.0 < ms <= 150.0


def test_live_output_only_guard_rejects_microphone_input() -> None:
    import pytest

    with pytest.raises(ValueError):
        ensure_output_only_input("Microphone Array (Realtek)")
    with pytest.raises(ValueError):
        ensure_output_only_input("Headset Mic")
    assert ensure_output_only_input(None) is True
    assert ensure_output_only_input("CABLE Output (VB-Audio Virtual Cable)") is True


def test_live_own_microphone_input_never_enters_seam() -> None:
    # The seam only ever sees speaker-output mixes: clips carry no mic
    # stem, and the guard refuses mic-like devices before any block flows.
    import pytest

    clip = make_game_clip()
    assert clip.sfx is not None
    with pytest.raises(ValueError):
        ensure_output_only_input("Microphone (USB Audio)")
    engine = build_live_engine()
    engine.set_enabled(True)
    out, ref = run_clip(engine, clip)
    assert out.shape == ref.shape


def test_live_44k_source_resampled_to_pipeline_filters() -> None:
    from silencio.resample import resample_stereo

    clip = make_song_clip()
    src44 = resample_stereo(clip.music, 48000, 44100)
    upsampled = resample_source_to_pipeline(src44, 44100)
    assert upsampled.shape[1] == 2
    assert upsampled.dtype == np.float32
    engine = build_live_engine()
    engine.set_enabled(True)
    outs = []
    for start in range(0, len(upsampled), 1024):
        outs.append(engine.process_block(upsampled[start : start + 1024]))
    out = np.concatenate(outs, axis=0)
    assert out.shape == upsampled.shape
    assert SAMPLE_RATE == 48000
    assert db(total_power(out), total_power(upsampled)) <= -2.0


def test_live_processing_is_local_only_no_network_imports() -> None:
    # ADR-0003: no audio leaves the machine. Static guardrail (not a seam
    # behavior test): the package must not import networking clients; the
    # separator is numpy-only with no weights and performs no I/O.
    import re
    from pathlib import Path

    pattern = re.compile(
        r"^\s*(import\s+(socket|urllib|http\.client|requests|websocket)\b"
        r"|from\s+(socket|urllib|http\.client|requests|websocket)\b)",
        re.MULTILINE,
    )
    for path in (Path(__file__).parent.parent / "src" / "silencio").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert pattern.search(text) is None, f"{path.name} imports a network client"


def test_live_graph_rejects_microphone_input_without_hardware() -> None:
    import pytest

    from silencio.graph import AudioGraph, GraphConfig

    engine = build_live_engine()
    with pytest.raises(ValueError):
        AudioGraph(engine, GraphConfig(input_device="Microphone (USB Audio)"))
    graph = AudioGraph(engine, GraphConfig())
    assert graph.latency_estimate_ms <= 150.0


def test_live_graph_rejects_over_budget_blocks_without_hardware() -> None:
    import pytest

    from silencio.graph import AudioGraph, GraphConfig

    engine = build_live_engine()
    with pytest.raises(ValueError):
        AudioGraph(engine, GraphConfig(block_frames=32768))
