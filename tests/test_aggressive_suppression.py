"""Suppression-first probes, separate from Vocal/SFX-preserving acceptance."""
import numpy as np
import pytest

from silencio.boost import build_boosted_live_engine
from silencio.clips import make_song_clip, run_clip
from silencio.metrics import db, total_power


def _filter(block, profile="aggressive", chunk=512):
    engine = build_boosted_live_engine(prefer="cpu", profile=profile, enabled=True)
    return np.concatenate([engine.process_block(block[i:i+chunk]) for i in range(0,len(block),chunk)])


@pytest.mark.parametrize("freq", [700, 2500, 7000])
def test_wide_instrumental_music_is_strongly_suppressed(freq):
    t = np.arange(3 * 48000) / 48000
    x = np.stack([.2*np.sin(2*np.pi*freq*t), .2*np.sin(2*np.pi*(freq+100)*t)], axis=1).astype(np.float32)
    y = _filter(x)
    assert db(total_power(y[48000:]), total_power(x[48000:])) < -25


def test_aggressive_reduces_music_more_than_balanced_and_keeps_some_vocal():
    clip = make_song_clip()
    def engine(profile):
        return build_boosted_live_engine(prefer="cpu", profile=profile, enabled=True)
    aggressive, ref = run_clip(engine("aggressive"), clip, stem="music")
    balanced, _ = run_clip(engine("balanced"), clip, stem="music")
    assert db(total_power(aggressive), total_power(ref)) < -15
    assert total_power(aggressive) < total_power(balanced)
    vocal, vocal_ref = run_clip(engine("aggressive"), clip, stem="vocal")
    assert db(total_power(vocal), total_power(vocal_ref)) > -12


def test_aggressive_output_is_independent_of_callback_chunk_size():
    x = make_song_clip().mix[:48000]
    np.testing.assert_array_equal(_filter(x, chunk=512), _filter(x, chunk=2048))


def test_aggressive_off_remains_bit_perfect():
    x = make_song_clip().mix[:4096]
    engine = build_boosted_live_engine(prefer="cpu", profile="aggressive", enabled=False)
    np.testing.assert_array_equal(engine.process_block(x), x)
