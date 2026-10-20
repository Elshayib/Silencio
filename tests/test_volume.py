from __future__ import annotations

from types import SimpleNamespace

import pytest

from silencio import desktop_runtime
from silencio.desktop_support import Preferences
from silencio.windows_audio import Endpoint, VolumeState
from silencio.volume import VolumeLink


class Control:
    def __init__(self, level=.8, muted=False):
        self.state = VolumeState(level, muted)
        self.closed = False
        self.writes = 0

    def read(self):
        assert not self.closed
        return self.state

    def set_level(self, level):
        self.state = VolumeState(level, self.state.muted)
        self.writes += 1

    def set_mute(self, muted):
        self.state = VolumeState(self.state.level, muted)
        self.writes += 1

    def close(self):
        self.closed = True


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    cable = Endpoint('cable', 'CABLE Input (VB-Audio Virtual Cable)')
    capture = Endpoint('capture', 'CABLE Output (VB-Audio Virtual Cable)')
    speakers = Endpoint('speakers', 'Speakers')
    controls = {'cable': Control(.02), 'speakers': Control(.86)}
    audio = SimpleNamespace(default=lambda: 'cable', endpoint_volume=lambda id: controls[id])

    class Graph:
        def __init__(self, *args, **kwargs):
            self.muted = False
        def start(self):
            pass
        def stop(self):
            pass
        def set_output_muted(self, muted):
            self.muted = muted

    monkeypatch.setattr(desktop_runtime, 'AudioGraph', Graph)
    monkeypatch.setattr(desktop_runtime, 'refresh_portaudio', lambda: None)
    monkeypatch.setattr(desktop_runtime, 'portaudio_index', lambda *a, **kw: 0)
    monkeypatch.setattr(desktop_runtime, 'reboot_pending', lambda *a: False)
    monkeypatch.setattr(desktop_runtime, 'build_boosted_live_engine', lambda **kw: None)
    worker = desktop_runtime.DesktopRuntime(tmp_path / 'state.json', Preferences())
    worker.audio = audio
    worker.route = SimpleNamespace(restore=lambda: None, activate=lambda *a: None,
                                  remember_volume=lambda state: None)
    worker.devices = lambda: ([speakers], cable, capture)
    return worker, controls


def test_starting_on_existing_cable_honors_windows_volume(runtime):
    worker, controls = runtime
    worker.start_audio()
    try:
        assert controls['speakers'].read().level == pytest.approx(.02), 'Windows slider ignored'
    finally:
        worker.stop_audio()


@pytest.mark.parametrize('state', [VolumeState(0, False), VolumeState(.2, True)])
def test_startup_zero_and_mute_never_render_audible_output(runtime, state):
    worker, controls = runtime
    controls['cable'].state = state
    worker.start_audio()
    try:
        assert controls['speakers'].read().muted, 'Speakers remain audible at zero/mute'
        assert worker.graph.muted
    finally:
        worker.stop_audio()


def test_live_volume_mute_unmute_and_shutdown(runtime):
    worker, controls = runtime
    worker.start_audio()
    for state in (VolumeState(.5, False), VolumeState(.1, False), VolumeState(0, False),
                  VolumeState(.2, False), VolumeState(.2, True), VolumeState(.2, False)):
        controls['cable'].state = state
        worker.volume.poll()
        actual = controls['speakers'].read()
        assert actual.level == state.level
        assert actual.muted == (state.muted or state.level == 0)
        assert worker.graph.muted == actual.muted
    # A last mute just before Quit must survive route restoration.
    controls['cable'].state = VolumeState(.2, True)
    worker.stop_audio()
    assert controls['speakers'].state == VolumeState(.2, True)
    assert all(c.closed for c in controls.values())


def test_new_route_inherits_speaker_volume_and_mute(runtime):
    worker, controls = runtime
    worker.audio.default = lambda: 'speakers'
    controls['speakers'].state = VolumeState(.3, True)
    worker.start_audio()
    try:
        assert controls['cable'].read() == VolumeState(.3, True)
        assert worker.graph.muted
    finally:
        worker.stop_audio()


def test_physical_controls_sync_back_without_polling_writes(runtime):
    worker, controls = runtime
    worker.start_audio()
    try:
        controls['speakers'].state = VolumeState(.12, True)
        worker.volume.poll()
        assert controls['cable'].read() == VolumeState(.12, True)
        before = [c.writes for c in controls.values()]
        for _ in range(20):
            worker.volume.poll()
        assert [c.writes for c in controls.values()] == before
    finally:
        worker.stop_audio()


def test_quantized_device_does_not_bounce_level_back():
    cable = Control(.12345)
    class Quantized(Control):
        def set_level(self, level):
            super().set_level(round(level, 2))
    speaker = Quantized()
    system = SimpleNamespace(endpoint_volume=lambda id: cable if id == 'c' else speaker)
    link = VolumeLink(system, 'c', 's', lambda muted: None, cable_is_default=True)
    for _ in range(10):
        link.poll()
    assert cable.read().level == .12345
    assert speaker.read().level == .12
    link.close()


def test_device_loss_mutes_graph_and_still_closes_handles(runtime):
    worker, controls = runtime
    worker.start_audio()
    graph = worker.graph
    def disconnected():
        raise OSError('device lost')
    controls['speakers'].read = disconnected
    with pytest.raises(OSError, match='device lost'):
        worker.volume.poll()
    assert graph.muted
    with pytest.raises(OSError, match='device lost'):
        worker.stop_audio()
    assert all(c.closed for c in controls.values())
    assert worker.graph is None and worker.volume is None


def test_failed_start_closes_volume_handles(runtime, monkeypatch):
    worker, controls = runtime
    def fail(_self):
        raise OSError('stream failed')
    monkeypatch.setattr(desktop_runtime.AudioGraph, 'start', fail)
    with pytest.raises(OSError, match='stream failed'):
        worker.start_audio()
    assert worker.volume is None
    assert all(c.closed for c in controls.values())


def test_output_reconnect_keeps_volume_and_mute(runtime):
    worker, controls = runtime
    worker.start_audio()
    controls['cable'].state = VolumeState(.15, True)
    worker.stop_audio()
    controls.update(cable=Control(.9), speakers=Control(1))
    worker.audio.default = lambda: 'speakers'
    worker.start_audio()
    try:
        assert controls['speakers'].read() == VolumeState(.15, True)
        assert worker.graph.muted
    finally:
        worker.stop_audio()


def test_crash_recovery_applies_last_volume_to_fallback_before_routing(tmp_path):
    from silencio.routing import RoutingLease
    cable = Endpoint('cable', 'CABLE Input (VB-Audio Virtual Cable)')
    speakers = Endpoint('speakers', 'Speakers')
    headset = Endpoint('headset', 'Headphones')
    defaults = {0: 'speakers', 1: 'speakers', 2: 'speakers'}
    control = Control(.9, False)
    def set_default(id, role):
        if id == 'speakers':
            assert control.state == VolumeState(.1, True), 'Fallback must mute BEFORE becoming default'
        defaults[role] = id
    system = SimpleNamespace(default=lambda role=0: defaults[role], set_default=set_default,
        endpoints=lambda: [cable, speakers], endpoint_volume=lambda id: control)
    path = tmp_path / 'routing.json'
    route = RoutingLease(system, path)
    route.activate(cable, headset, VolumeState(.2, False))
    route.remember_volume(VolumeState(.1, True))
    # Fresh object simulates the independent recovery process; headset is gone.
    RoutingLease(system, path).restore()
    assert all(id == 'speakers' for id in defaults.values())
    assert control.closed and not path.exists()


def test_crash_recovery_does_not_change_user_selected_output_volume(tmp_path):
    from silencio.routing import RoutingLease
    cable = Endpoint('cable', 'CABLE Input (VB-Audio Virtual Cable)')
    speakers = Endpoint('speakers', 'Speakers')
    defaults = {0: 'speakers', 1: 'speakers', 2: 'speakers'}
    system = SimpleNamespace(default=lambda role=0: defaults[role],
        set_default=lambda id, role: defaults.update({role: id}), endpoints=lambda: [cable, speakers],
        endpoint_volume=lambda id: pytest.fail('Explicit user route must retain its own controls'))
    route = RoutingLease(system, tmp_path / 'routing.json')
    route.activate(cable, speakers, VolumeState(.1, True))
    defaults.update({0: 'speakers', 1: 'speakers', 2: 'speakers'})
    route.restore()
