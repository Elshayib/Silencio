"""Ticket 05 acceptance: setup plus robustness (offline, no hardware).

Seams (pre-agreed): setup plan, startup/autostart entry, blocked-capture
monitor, graph device-change recovery. All offline: no virtual cable,
no live driver, no network. Live WASAPI/tray/hotkey AB stays manual
per the spec.

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_setup_finds_virtual_output_by_name() -> None:
    from silencio.setup import find_virtual_output

    assert find_virtual_output(["Speakers (Realtek)", "CABLE Output (VB-Audio Virtual Cable)"]) == (
        "CABLE Output (VB-Audio Virtual Cable)"
    )
    assert find_virtual_output(["Speakers", "Headphones"]) is None
    assert find_virtual_output([]) is None
    # Render-path-only scope: a virtual-named microphone is never suggested.
    assert find_virtual_output(["Virtual Microphone Array"]) is None
    assert (
        find_virtual_output(["Virtual Microphone Array", "CABLE Output (VB-Audio Virtual Cable)"])
        == "CABLE Output (VB-Audio Virtual Cable)"
    )


def test_setup_plan_tracks_first_run_checklist() -> None:
    from silencio.setup import build_setup_plan

    fresh = build_setup_plan(device_names=["Speakers"])
    assert fresh.passed is False
    assert len(fresh.steps) == 6
    assert all("PASS" not in s.name for s in fresh.steps)

    done = build_setup_plan(
        device_names=["CABLE Output (VB-Audio Virtual Cable)"],
        admin=True,
        default_is_cable=True,
        exclusive_off=True,
        apps_restarted=True,
        rebooted=True,
    )
    assert done.passed is True
    assert "Default Playback" in done.steps[2].name


def test_auto_start_entry_round_trip_tmp(tmp_path: Path) -> None:
    from silencio.startup import is_auto_start_enabled, set_auto_start, startup_entry_path

    entry = startup_entry_path(base=tmp_path)
    assert is_auto_start_enabled(entry) is False
    set_auto_start(True, entry=entry)
    assert is_auto_start_enabled(entry) is True
    set_auto_start(False, entry=entry)
    assert is_auto_start_enabled(entry) is False


def test_toggle_persists_for_automatic_startup(tmp_path: Path) -> None:
    from silencio.engine import SilencioEngine
    from silencio.state import ToggleStateStore

    store_path = tmp_path / "state.json"
    engine = SilencioEngine(state_store=ToggleStateStore(store_path))
    engine.set_enabled(True)
    # A fresh engine on next login restores ON without user action.
    revived = SilencioEngine(state_store=ToggleStateStore(store_path))
    assert revived.enabled is True


def test_is_admin_override_is_testable(monkeypatch: pytest.MonkeyPatch) -> None:
    from silencio.setup import is_admin

    monkeypatch.setenv("SILENCIO_ASSUME_ADMIN", "1")
    assert is_admin() is True
    monkeypatch.setenv("SILENCIO_ASSUME_ADMIN", "0")
    assert is_admin() is False


def test_blocked_capture_flags_sustained_silence_without_crashing() -> None:
    import numpy as np

    from silencio.capture import BlockedCaptureMonitor

    monitor = BlockedCaptureMonitor(blocks_to_flag=4)
    silent = np.zeros((1024, 2), dtype=np.float32)
    assert monitor.push(silent) == "silent"
    assert monitor.push(silent) == "silent"
    assert monitor.push(silent) == "silent"
    assert monitor.push(silent) == "blocked-suspected"
    assert monitor.status == "blocked-suspected"
    sounding = (np.ones((1024, 2), dtype=np.float32) * 0.2).astype(np.float32)
    assert monitor.push(sounding) == "ok"
    assert monitor.status == "ok"


def test_blocked_capture_message_is_honest_limitation() -> None:
    from silencio.capture import format_blocked_message

    message = format_blocked_message("blocked-suspected")
    assert "known limitation" in message.lower()
    assert "crash" not in message.lower() or "never" in message.lower() or "not" in message.lower()
    assert "DRM" in message or "drm" in message.lower()
    assert "exclusive" in message.lower()


def test_graph_device_change_recovers_without_restart_offline() -> None:
    import numpy as np

    from silencio.graph import AudioGraph, GraphConfig
    from silencio.live import build_live_engine

    engine = build_live_engine()
    engine.set_enabled(True)
    graph = AudioGraph(engine, GraphConfig())
    silent = np.zeros((1024, 2), dtype=np.float32)
    graph.observe_input(silent)
    assert graph.capture_status in ("silent", "blocked-suspected", "ok")
    graph.on_device_change()
    assert engine.enabled is True
    assert graph.needs_reopen is True
    assert graph.capture_status == "ok"
    graph.reopen()
    assert graph.needs_reopen is False
    assert engine.enabled is True
    out = engine.process_block(np.zeros((512, 2), dtype=np.float32))
    assert out.shape == (512, 2)
    assert np.all(np.isfinite(out))


def test_setup_cli_reports_guided_plan_offline(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from silencio.cli import main

    code = main(["--setup", "--state", str(tmp_path / "state.json")])
    assert code in (0, 1)
    out = capsys.readouterr().out.lower()
    assert "first-run setup" in out
    assert "default playback" in out
    assert "exclusive-mode" in out
    assert "known limitation" in out


def test_startup_cli_enables_and_disables_offline(tmp_path: Path) -> None:
    from silencio.cli import main
    from silencio.startup import is_auto_start_enabled

    entry = tmp_path / "Startup" / "Silencio.bat"
    assert main(["--install-startup", "--startup-path", str(entry)]) == 0
    assert is_auto_start_enabled(entry) is True
    assert main(["--remove-startup", "--startup-path", str(entry)]) == 0
    assert is_auto_start_enabled(entry) is False


def test_diagnose_cli_reports_toggle_and_limits(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from silencio.cli import main

    code = main(["--diagnose", "--state", str(tmp_path / "state.json")])
    assert code == 0
    out = capsys.readouterr().out.lower()
    assert "toggle" in out
    assert "150ms" in out
    assert "known limitation" in out or "drm" in out
