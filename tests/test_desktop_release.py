from __future__ import annotations

import json
from pathlib import Path

import pytest

from silencio.desktop_support import Preferences, consume_command, request_existing
from silencio.routing import RoutingLease
from silencio.windows_audio import Endpoint

CABLE = Endpoint("cable", "CABLE Input (VB-Audio Virtual Cable)")
SPEAKER = Endpoint("speaker", "Speakers (Realtek)")
HEADSET = Endpoint("headset", "Headphones")


class FakeAudio:
    def __init__(self) -> None:
        self.outputs = [CABLE, SPEAKER, HEADSET]
        self.defaults: dict[int, str | None] = {0: "speaker", 1: "speaker", 2: "headset"}
        self.fail_role: int | None = None

    def endpoints(self, flow: int = 0, states: int = 1) -> list[Endpoint]:
        assert flow == 0  # Runtime routing must never touch recording devices.
        return self.outputs

    def default(self, role: int = 0, flow: int = 0) -> str | None:
        assert flow == 0
        return self.defaults[role]

    def set_default(self, endpoint_id: str, role: int) -> None:
        if role == self.fail_role:
            self.fail_role = None
            raise OSError("simulated Windows failure")
        self.defaults[role] = endpoint_id


def test_quit_restores_each_original_role(tmp_path: Path) -> None:
    audio = FakeAudio()
    original = dict(audio.defaults)
    route = RoutingLease(audio, tmp_path / "routing.json")
    route.activate(CABLE, SPEAKER)
    assert set(audio.defaults.values()) == {"cable"}
    route.restore()
    assert audio.defaults == original
    assert not route.path.exists()


def test_partial_routing_failure_rolls_back(tmp_path: Path) -> None:
    audio = FakeAudio()
    audio.fail_role = 1
    route = RoutingLease(audio, tmp_path / "routing.json")
    with pytest.raises(OSError):
        route.activate(CABLE, SPEAKER)
    assert audio.defaults == {0: "speaker", 1: "speaker", 2: "headset"}
    assert not route.path.exists()


def test_new_process_recovers_journal_without_live_python_state(tmp_path: Path) -> None:
    audio = FakeAudio()
    path = tmp_path / "routing.json"
    RoutingLease(audio, path).activate(CABLE, SPEAKER)
    RoutingLease(audio, path).restore()
    assert audio.defaults[0] == "speaker"


def test_restore_respects_explicit_user_change(tmp_path: Path) -> None:
    audio = FakeAudio()
    route = RoutingLease(audio, tmp_path / "routing.json")
    route.activate(CABLE, SPEAKER)
    audio.defaults[0] = "headset"
    route.restore()
    assert audio.defaults == {0: "headset", 1: "speaker", 2: "headset"}


def test_no_physical_device_keeps_journal_until_reconnected(tmp_path: Path) -> None:
    audio = FakeAudio()
    route = RoutingLease(audio, tmp_path / "routing.json")
    route.activate(CABLE, SPEAKER)
    audio.outputs = [CABLE]
    route.restore()
    assert route.path.exists()
    audio.outputs = [CABLE, SPEAKER]
    route.restore()
    assert set(audio.defaults.values()) == {"speaker"}
    assert not route.path.exists()


def test_existing_manual_cable_default_restores_real_speakers(tmp_path: Path) -> None:
    audio = FakeAudio()
    audio.defaults = {0: "cable", 1: "cable", 2: None}
    route = RoutingLease(audio, tmp_path / "routing.json")
    route.activate(CABLE, SPEAKER)
    route.restore()
    assert set(audio.defaults.values()) == {"speaker"}


def test_journal_write_failure_does_not_redirect_audio(tmp_path: Path) -> None:
    audio = FakeAudio()
    parent = tmp_path / "file"
    parent.write_text("occupied")
    route = RoutingLease(audio, parent / "routing.json")
    with pytest.raises(OSError):
        route.activate(CABLE, SPEAKER)
    assert audio.defaults[0] == "speaker"


def test_virtual_output_feedback_is_rejected(tmp_path: Path) -> None:
    audio = FakeAudio()
    with pytest.raises(ValueError):
        RoutingLease(audio, tmp_path / "routing.json").activate(CABLE, CABLE)


@pytest.mark.parametrize("payload", ["{", "null", "[]", '{"profile":"unknown","output_id":9,"start_with_windows":false}'])
def test_preferences_recover_from_bad_or_old_configuration(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(payload)
    prefs = Preferences.load(path)
    assert prefs.profile == "speech"
    assert prefs.output_id == ""


def test_preferences_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    Preferences("speech-fast", "stable-endpoint-id", False).save(path)
    assert Preferences.load(path) == Preferences("speech-fast", "stable-endpoint-id", False)


def test_simultaneous_launch_requests_remain_atomic(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from silencio.routing import save_json

    path = tmp_path / "command.json"
    with ThreadPoolExecutor(max_workers=8) as writers:
        list(writers.map(lambda value: save_json(path, {"request": value}), range(32)))
    assert json.loads(path.read_text())["request"] in range(32)


def test_commands_are_consumed_once_and_expire(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    request_existing(state, "show")
    assert consume_command(state) == "show"
    assert consume_command(state) is None
    state.with_suffix(".command.json").write_text(json.dumps({"action": "quit", "at": 1}))
    assert consume_command(state) is None


@pytest.mark.parametrize("device_rate", [88200, 96000, 176400, 192000])
def test_high_rate_speakers_need_no_manual_format_change(device_rate: int) -> None:
    import numpy as np
    from silencio.resample import BandlimitedResampler

    source = np.sin(2 * np.pi * 1000 * np.arange(4800) / 48000).astype(np.float32)
    stereo = np.column_stack((source, -source))
    up = BandlimitedResampler(48000, device_rate)
    device_audio = np.concatenate([up.push(part) for part in np.array_split(stereo, 13)])
    assert len(device_audio) == device_rate // 10
    back = BandlimitedResampler(device_rate, 48000).push(device_audio)
    assert np.all(np.isfinite(back))
    assert np.max(np.abs(back[:, 0] + back[:, 1])) < 1e-6
    assert .68 < float(np.sqrt(np.mean(back[200:, 0] ** 2))) < .73


def test_existing_driver_is_never_reinstalled_even_with_renamed_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from silencio import driver

    monkeypatch.setattr(driver, "driver_installed", lambda: True)
    with pytest.raises(RuntimeError, match="already installed"):
        driver.install_driver(FakeAudio(), tmp_path / "restart.json")


def test_damaged_driver_payload_is_rejected_before_elevation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from silencio import driver

    directory = tmp_path / "vbcable"
    directory.mkdir()
    (directory / "driver.exe").write_bytes(b"changed")
    (tmp_path / "vbcable-manifest.json").write_text(json.dumps({"files": {"driver.exe": "0" * 64}}))
    monkeypatch.setattr(driver, "driver_installed", lambda: False)
    monkeypatch.setattr(driver, "driver_directory", lambda: directory)
    with pytest.raises(RuntimeError, match="damaged"):
        driver.install_driver(FakeAudio(), tmp_path / "restart.json")
