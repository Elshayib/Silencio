"""Regressions for the actual live launch and callback paths."""
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from silencio import cli
from silencio.engine import SilencioEngine
from silencio.graph import AudioGraph, GraphConfig
from silencio.state import ToggleStateStore


@pytest.fixture
def audio(monkeypatch):
    streams = []
    devices = [
        dict(name="CABLE Output (VB-Audio Virtual Cable)", max_input_channels=2, max_output_channels=0, hostapi=0),
        dict(name="Speakers (Realtek)", max_input_channels=0, max_output_channels=2, hostapi=0),
        dict(name="Microphone Array", max_input_channels=2, max_output_channels=0, hostapi=0),
        dict(name="CABLE Input (VB-Audio Virtual Cable)", max_input_channels=0, max_output_channels=2, hostapi=0),
    ]
    class Stream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.active = False
            self.latency = (0.01, 0.01)
            streams.append(self)
        def start(self):
            self.active = True
        def stop(self):
            self.active = False
        def close(self):
            pass
    def query(device=None, kind=None):
        if device is None:
            return devices
        if isinstance(device, str):
            device = next(i for i, d in enumerate(devices) if device.lower() in d['name'].lower())
        return devices[device]
    backend = SimpleNamespace(Stream=Stream, query_devices=query,
        query_hostapis=lambda: [dict(name="Windows DirectSound")], default=SimpleNamespace(device=(2, 3)))
    monkeypatch.setitem(sys.modules, "sounddevice", backend)
    monkeypatch.setattr(cli, "register_hotkey", lambda *a: None)
    monkeypatch.setattr("silencio.boost.accelerator_available", lambda: False)
    return streams


def test_run_on_starts_filter_instead_of_only_writing_state(audio, monkeypatch, tmp_path):
    import time
    monkeypatch.setattr(time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert cli.main(["--run", "--on", "--backend", "cpu", "--state", str(tmp_path / "state.json")]) == 0
    assert len(audio) == 1, "--run --on must actually open the live audio stream"


def test_cli_toggle_reaches_running_audio_callback(audio, tmp_path):
    path = tmp_path / "state.json"
    store = ToggleStateStore(path)
    store.save(False)
    engine = SilencioEngine(processor=lambda x: x * 0, state_store=store)
    graph = AudioGraph(engine, GraphConfig(input_device=0, output_device=1))
    graph.start()
    assert cli.main(["--on", "--state", str(path)]) == 0
    # The control loop must reload state away from the real-time callback.
    if hasattr(graph, "poll"):
        graph.poll()
    block = np.ones((1024, 2), np.float32) * 0.2
    out = np.empty_like(block)
    audio[0].kwargs['callback'](block, out, 1024, None, None)
    graph.stop()
    assert engine.enabled, "external --on is currently ignored by a running graph"
    assert np.max(np.abs(out[-128:])) == 0


def test_numeric_microphone_input_is_rejected_before_open(audio):
    graph = AudioGraph(SilencioEngine(), GraphConfig(input_device=2, output_device=1))
    with pytest.raises(ValueError, match="microphone|virtual cable"):
        graph.start()
    assert not audio


def test_rendering_back_to_cable_is_rejected(audio):
    graph = AudioGraph(SilencioEngine(), GraphConfig(input_device=0, output_device=3))
    with pytest.raises(ValueError, match="feedback|real speakers"):
        graph.start()
    assert not audio


def test_bad_external_state_does_not_disable_running_filter(tmp_path):
    path = tmp_path / "state.json"
    store = ToggleStateStore(path)
    store.save(True)
    engine = SilencioEngine(state_store=store)
    path.write_text('{"enabled":', encoding="utf-8")
    assert engine.reload_state() is False
    assert engine.enabled is True


def test_live_instance_prevents_duplicate_renderers(tmp_path):
    from silencio.runtime import LiveInstance
    a = LiveInstance(tmp_path / "state.json")
    b = LiveInstance(tmp_path / "state.json")
    assert a.acquire()
    try:
        assert not b.acquire()
    finally:
        a.close()
    assert b.acquire()
    b.close()


def test_wasapi_uses_native_rates_and_bridges_callbacks(audio, monkeypatch):
    backend = sys.modules["sounddevice"]
    backend.query_hostapis = lambda: [dict(name="Windows WASAPI")]
    backend.query_devices(0)["default_samplerate"] = 44100
    backend.query_devices(1)["default_samplerate"] = 48000
    backend.InputStream = backend.Stream
    backend.OutputStream = backend.Stream
    graph = AudioGraph(SilencioEngine(), GraphConfig(block_frames=480, input_device=0, output_device=1))
    graph.start()
    capture, render = audio
    assert capture.kwargs["samplerate"] == 44100
    assert capture.kwargs["blocksize"] == 441
    assert render.kwargs["samplerate"] == 48000
    assert render.kwargs["blocksize"] == 480
    # Drain priming and feed enough audio to exercise conversion across edges.
    out = np.empty((480, 2), np.float32)
    for _ in range(2):
        render.kwargs["callback"](out, 480, None, None)
    block = np.full((441, 2), .2, np.float32)
    for _ in range(3):
        capture.kwargs["callback"](block, 441, None, None)
    render.kwargs["callback"](out, 480, None, None)
    # Startup fades for 2 ms; the rest of the converted audio is unchanged.
    np.testing.assert_allclose(out[96:], .2, atol=1e-6)
    assert graph.last_error is None
    graph.stop()


def test_processing_exception_mutes_music_and_keeps_callback_alive(audio):
    def broken(block):
        raise RuntimeError("DSP failure")
    graph = AudioGraph(SilencioEngine(processor=broken), GraphConfig(input_device=0, output_device=1))
    graph.engine.set_enabled(True)
    graph.start()
    out = np.empty((512, 2), np.float32)
    audio[0].kwargs['callback'](np.full_like(out, .2), out, 512, None, None)
    assert graph.last_error == "DSP failure"
    assert not np.any(out)
    assert graph.is_running
    graph.stop()


def test_off_never_runs_or_depends_on_speech_processor(audio):
    def broken(block):
        raise RuntimeError("Disabled DSP must not interrupt playback")
    graph = AudioGraph(SilencioEngine(processor=broken), GraphConfig(input_device=0, output_device=1))
    graph.start()
    block = np.full((480, 2), .2, np.float32)
    out = np.empty_like(block)
    audio[0].kwargs['callback'](block, out, 480, None, None)
    np.testing.assert_array_equal(out, block)
    assert graph.last_error is None
    graph.stop()


def test_wasapi_gap_recovery_does_not_make_clicks(audio):
    backend = sys.modules['sounddevice']
    backend.query_hostapis = lambda: [dict(name='Windows WASAPI')]
    for index in (0, 1):
        backend.query_devices(index)['default_samplerate'] = 48000
    backend.InputStream = backend.Stream
    backend.OutputStream = backend.Stream
    graph = AudioGraph(SilencioEngine(), GraphConfig(block_frames=480, input_device=0, output_device=1))
    graph.start()
    capture, render = audio
    out = np.empty((480, 2), np.float32)
    block = np.full_like(out, .2)
    result = []
    for i in range(30):
        # An input callback delayed by Windows consumes the bridge reserve.
        if i not in (10, 11, 12, 13):
            capture.kwargs['callback'](block, 480, None, None)
        render.kwargs['callback'](out, 480, None, None)
        result.append(out.copy())
    joined = np.concatenate(result)
    assert graph.underruns > 0
    assert np.max(np.abs(np.diff(joined[:, 0]))) < .01, 'abrupt gaps make audible clicks'
    assert np.max(joined) == pytest.approx(.2)
    graph.stop()


def test_malformed_driver_block_never_bypasses_music(audio):
    graph = AudioGraph(SilencioEngine(), GraphConfig(input_device=0,output_device=1))
    graph.start()
    out = np.empty((512,2),np.float32)
    audio[0].kwargs['callback'](np.full((513,2),.2,np.float32),out,512,None,None)
    assert not out.any()
    assert 'invalid stereo' in graph.last_error
    graph.stop()


@pytest.mark.parametrize('wasapi', [False, True])
@pytest.mark.parametrize('enabled', [False, True])
def test_output_mute_silences_already_buffered_audio_and_resumes(audio, wasapi, enabled):
    backend = sys.modules['sounddevice']
    if wasapi:
        backend.query_hostapis = lambda: [dict(name='Windows WASAPI')]
        for i in (0, 1):
            backend.query_devices(i)['default_samplerate'] = 48000
        backend.InputStream = backend.Stream
        backend.OutputStream = backend.Stream
    engine = SilencioEngine(processor=lambda x: x * .5)
    engine.set_enabled(enabled)
    graph = AudioGraph(engine, GraphConfig(block_frames=480, input_device=0, output_device=1))
    graph.start()
    block = np.full((480, 2), .2, np.float32)
    out = np.empty_like(block)
    def render():
        if wasapi:
            audio[0].kwargs['callback'](block, 480, None, None)
            audio[1].kwargs['callback'](out, 480, None, None)
        else:
            audio[0].kwargs['callback'](block, out, 480, None, None)
    try:
        for _ in range(5):
            render()
        assert np.any(out)
        graph.set_output_muted(True)
        render()
        assert not np.any(out), 'Mute must discard even audio queued before the change'
        for _ in range(5):
            render()
            assert not np.any(out)
        graph.set_output_muted(False)
        for _ in range(5):
            render()
        np.testing.assert_allclose(out, .1 if enabled else .2, atol=1e-6)
    finally:
        graph.stop()
