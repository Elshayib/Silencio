"""Actual frame bridge: callback jitter must not cause a full-scale click."""
import numpy as np
import pytest

from silencio.playback import PlaybackBridge


def test_bounded_overflow_crossfades_discarded_audio():
    bridge = PlaybackBridge(480,48000)
    out = np.empty((480,2),np.float32)
    bridge.push(np.full((1440,2),.5,np.float32))
    bridge.render(out)
    bridge.push(np.full((1920,2),-.5,np.float32))
    bridge.render(out)
    assert bridge.overruns == 1
    assert np.max(np.abs(np.diff(np.r_[.5,out[:,0]]))) < .02
    assert np.all(out[-100:] == -.5)
    assert bridge._size <= bridge.capacity


def test_regular_audio_is_unchanged_after_initial_fade():
    rng = np.random.default_rng(42)
    audio = rng.normal(0,.1,(4800,2)).astype(np.float32)
    bridge = PlaybackBridge(480,48000)
    bridge.push(audio[:960])
    out = np.empty((480,2),np.float32)
    bridge.render(out)  # Startup fade only.
    for i in range(960,len(audio),480):
        bridge.push(audio[i:i+480])
        bridge.render(out)
        np.testing.assert_array_equal(out,audio[i-480:i])
    assert bridge.underruns == bridge.overruns == 0


@pytest.mark.parametrize('remainder', [0,1,40,479])
def test_missing_audio_fades_then_rebuffers_before_resuming(remainder):
    bridge = PlaybackBridge(480,48000)
    bridge.push(np.full((960 + remainder,2),.3,np.float32))
    out = np.empty((480,2),np.float32)
    bridge.render(out)
    bridge.render(out)
    bridge.render(out)
    assert out[-1,0] == 0
    assert np.max(np.abs(np.diff(np.r_[.3,out[:,0]]))) < .01
    bridge.push(np.full((480,2),.3,np.float32))
    bridge.render(out)
    assert not out.any()
    bridge.push(np.full((480,2),.3,np.float32))
    bridge.render(out)
    assert np.max(np.abs(np.diff(np.r_[0,out[:,0]]))) < .01
    assert bridge.underruns == 1
