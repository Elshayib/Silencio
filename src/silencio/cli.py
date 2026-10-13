"""CLI entry: ``python -m silencio``.

- ``--check`` runs an offline self-check through the tested buffer seam
  (no audio hardware needed) and prints a manual-AB record.
- ``--clips`` runs the ticket 02 acceptance harness (three clips plus
  crowd/unison probes) through the same seam and prints PASS/FAIL numbers.
- ``--soak`` runs the ticket 04 CPU soak (continuous playback timing
  plus measured delay) through the same seam; ``--backend`` selects the
  separator pass and ``--soak-seconds`` sets the length.
- ``--acceptance`` runs the ticket 06 full v1 acceptance (three-clip live
  AB plus gapless loudness-matched toggle AB plus stability soak with
  device change) through the same seam; ``--backend`` and
  ``--soak-seconds`` apply to its soak leg.
- ``--setup`` prints guided first-run setup (virtual output, Default
  Playback, exclusive-mode off, reboot, app restart) offline.
- ``--install-startup`` / ``--remove-startup`` manage auto-start on login.
- ``--diagnose`` prints toggle, auto-start, latency, and known limitations.
- ``--run`` starts the live loopback graph (needs VB-Cable + sounddevice).
- ``--toggle`` flips the persisted global toggle without starting audio.
- ``--list-devices`` prints PortAudio devices for cable selection.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from silencio.engine import MAX_SWITCH_SAMPLES_50MS, SAMPLE_RATE, SilencioEngine
from silencio.graph import (
    AudioGraph,
    GraphConfig,
    build_engine,
    default_state_path,
    register_hotkey,
)
from silencio.harness import format_report, run_acceptance
from silencio.live import estimate_end_to_end_ms


def offline_check() -> int:
    print("Silencio ticket 01 offline check (buffer seam, no hardware)")
    rng = np.random.default_rng(7)
    engine = SilencioEngine()
    probe = rng.uniform(-0.5, 0.5, size=(4800, 2)).astype(np.float32)
    out = engine.process_block(probe)
    bit_perfect = bool(np.array_equal(out, probe))
    print(f"  OFF bit-perfect passthrough: {'PASS' if bit_perfect else 'FAIL'}")

    engine.set_enabled(True)
    engine.process_block(np.zeros((4096, 2), dtype=np.float32))
    out_on = engine.process_block(probe)
    loudness_parity = bool(np.array_equal(out_on, probe))
    print(f"  ON loudness parity (gain 1.0): {'PASS' if loudness_parity else 'FAIL'}")

    print(f"  switch budget: ramp {engine.ramp_samples} <= {MAX_SWITCH_SAMPLES_50MS} samples (50ms)")
    print(f"  switch time: {engine.switch_time_ms:.1f}ms (<50ms required)")
    print(f"  sample rate: {SAMPLE_RATE}Hz stereo, no mono downmix")
    block_ms = 1024.0 / float(SAMPLE_RATE) * 1000.0
    print(f"  block budget: 1024 frames = {block_ms:.1f}ms + ramp {engine.switch_time_ms:.1f}ms")
    print("  (full 150ms end-to-end proof lands with ticket 04 soak; 01 proves switch <50ms)")
    print("Manual live AB still required: browser/movie/game audible OFF,")
    print("mid-sound toggle gapless, headphone replug recovers without restart.")
    return 0 if (bit_perfect and loudness_parity) else 1


def list_devices() -> int:
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice not installed; pip install .[audio]", file=sys.stderr)
        return 2
    print(sd.query_devices())
    print("Set the virtual cable output as Default Playback (Windows Sound),")
    print("disable exclusive-mode on it, then use its loopback as input and")
    print("your real speakers as output.")
    return 0


def run_soak_cli(backend: str, seconds: float) -> int:
    """Ticket 04 soak through the buffer seam (no hardware needed)."""
    from silencio.boost import build_boosted_live_engine, describe_accelerator
    from silencio.soak import SoakConfig, format_soak_report, run_soak

    if backend not in ("auto", "cpu", "gpu"):
        print(f'backend must be "auto", "cpu" or "gpu", got {backend!r}', file=sys.stderr)
        return 2
    report = run_soak(
        engine_factory=lambda: build_boosted_live_engine(prefer=backend, enabled=True),
        config=SoakConfig(duration_s=seconds),
    )
    print(f"backend: requested={backend} hardware={describe_accelerator()}")
    print(format_soak_report(report))
    print("Manual live AB still required: driver jitter, headphone replug, loudness check.")
    return 0 if report.passed else 1


def run_acceptance_cli(backend: str, seconds: float) -> int:
    """Ticket 06 full v1 acceptance through the buffer seam (no hardware needed)."""
    from silencio.acceptance import V1Config, format_v1_report, run_v1_acceptance
    from silencio.boost import describe_accelerator

    if backend not in ("auto", "cpu", "gpu"):
        print(f'backend must be "auto", "cpu" or "gpu", got {backend!r}', file=sys.stderr)
        return 2
    report = run_v1_acceptance(V1Config(backend=backend, soak_seconds=float(seconds)))
    print(f"backend: requested={backend} hardware={describe_accelerator()}")
    print(format_v1_report(report))
    return 0 if report.passed else 1


def _query_device_names() -> list[str] | None:
    """Best-effort PortAudio device names; None when unavailable offline."""
    try:
        import sounddevice as sd
    except ImportError:
        return None
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    names: list[str] = []
    try:
        for entry in devices:
            if isinstance(entry, dict):
                name = entry.get("name", "")
            else:
                name = getattr(entry, "name", "")
            names.append(str(name))
    except Exception:
        return None
    return names


def run_setup_cli(state_path: Path, startup_entry: Path | None = None) -> int:
    """Ticket 05 guided first-run setup (offline, no hardware needed)."""
    from silencio.setup import build_setup_plan, format_setup_plan
    from silencio.startup import format_startup_status, is_auto_start_enabled, startup_entry_path

    device_names = _query_device_names()
    plan = build_setup_plan(device_names=device_names)
    print(format_setup_plan(plan))
    entry = startup_entry if startup_entry is not None else startup_entry_path()
    print(format_startup_status(is_auto_start_enabled(entry), entry))
    print(f"toggle state file: {state_path}")
    print("input = cable loopback (never a microphone), output = real speakers.")
    return 0 if plan.passed else 1


def run_startup_cli(enabled: bool, startup_entry: Path | None = None) -> int:
    """Ticket 05 auto-start install/remove (file operation only)."""
    from silencio.startup import is_auto_start_enabled, set_auto_start, startup_entry_path

    entry = startup_entry if startup_entry is not None else startup_entry_path()
    path = set_auto_start(bool(enabled), entry=entry)
    state = "ON" if is_auto_start_enabled(path) else "OFF"
    action = "installed" if bool(enabled) else "removed"
    print(f"auto-start {action}: {state} ({path})")
    return 0


def run_diagnose_cli(state_path: Path, startup_entry: Path | None = None) -> int:
    """Ticket 05 diagnose: toggle, auto-start, latency, known limitations."""
    from silencio.boost import describe_accelerator
    from silencio.capture import BLOCKED_MESSAGE
    from silencio.graph import build_engine
    from silencio.startup import format_startup_status, is_auto_start_enabled, startup_entry_path

    engine = build_engine(state_path)
    entry = startup_entry if startup_entry is not None else startup_entry_path()
    print(f"toggle={'ON' if engine.enabled else 'OFF'} persisted to {state_path}")
    print(format_startup_status(is_auto_start_enabled(entry), entry))
    print(f"backend: {describe_accelerator()} (CPU floor, GPU boost when present)")
    print(f"latency estimate: {estimate_end_to_end_ms():.1f}ms (budget 150ms)")
    print("local-only: no audio leaves this machine; mic inputs never processed.")
    print(f"known limitation: {BLOCKED_MESSAGE}")
    print("device change: unplug/replug recovers without restart (reopen flagged).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="silencio")
    parser.add_argument("--check", action="store_true", help="offline seam check")
    parser.add_argument("--clips", action="store_true", help="ticket 02 clip harness")
    parser.add_argument("--soak", action="store_true", help="ticket 04 CPU soak")
    parser.add_argument("--acceptance", action="store_true", help="ticket 06 full v1 acceptance")
    parser.add_argument("--backend", default="auto", help="soak separator pass: auto/cpu/gpu")
    parser.add_argument("--soak-seconds", type=float, default=30.0)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--setup", action="store_true", help="ticket 05 guided first-run setup")
    parser.add_argument("--diagnose", action="store_true", help="ticket 05 toggle/startup/latency report")
    parser.add_argument("--install-startup", action="store_true", help="enable auto-start on login")
    parser.add_argument("--remove-startup", action="store_true", help="disable auto-start on login")
    parser.add_argument("--startup-path", type=Path, default=None)
    parser.add_argument("--run", action="store_true", help="start live graph")
    parser.add_argument("--toggle", action="store_true", help="flip persisted toggle")
    parser.add_argument("--on", action="store_true")
    parser.add_argument("--off", action="store_true")
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args(argv)

    state_path = args.state if args.state is not None else default_state_path()
    startup_path: Path | None = args.startup_path

    if args.check:
        return offline_check()
    if args.clips:
        report = run_acceptance()
        print(format_report(report))
        return 0 if report.passed else 1
    if args.soak:
        return run_soak_cli(args.backend, float(args.soak_seconds))
    if args.acceptance:
        return run_acceptance_cli(args.backend, float(args.soak_seconds))
    if args.list_devices:
        return list_devices()
    if args.setup:
        return run_setup_cli(state_path, startup_path)
    if args.diagnose:
        return run_diagnose_cli(state_path, startup_path)
    if args.install_startup:
        return run_startup_cli(True, startup_path)
    if args.remove_startup:
        return run_startup_cli(False, startup_path)
    if args.toggle:
        engine = build_engine(state_path)
        engine.set_enabled(not engine.enabled)
        print(f"toggle={'ON' if engine.enabled else 'OFF'} persisted to {state_path}")
        return 0
    if args.on or args.off:
        engine = build_engine(state_path)
        engine.set_enabled(bool(args.on))
        print(f"toggle={'ON' if engine.enabled else 'OFF'} persisted to {state_path}")
        return 0
    if args.run:
        from silencio.boost import build_boosted_live_engine, describe_accelerator

        engine = build_boosted_live_engine(state_path=state_path, prefer="auto")
        graph = AudioGraph(engine, GraphConfig())
        print(f"starting live Vocal filter (toggle={'ON' if engine.enabled else 'OFF'})")
        print(f"backend: {describe_accelerator()} (CPU floor, GPU boost when present)")
        print("ON: Vocal plus SFX with Music reduced; OFF: original mix bit-perfect.")
        print(f"latency estimate: {estimate_end_to_end_ms():.1f}ms (budget 150ms)")
        print("local-only: no audio leaves this machine; mic inputs never processed.")
        print("Setup: virtual output = Default Playback, exclusive-mode off,")
        print("input = cable loopback (never a microphone), output = real speakers.")
        hotkey_handle = register_hotkey(graph.toggle)
        if hotkey_handle is None:
            print("hotkey: Ctrl+Alt+M unavailable (pip install .[tray]); use --toggle in another shell.")
        else:
            print("hotkey: Ctrl+Alt+M toggles live.")
        try:
            graph.start()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("running; Ctrl+C to stop.")
        try:
            import time

            while True:
                time.sleep(0.5)
                if graph.needs_reopen:
                    graph.reopen()
        except KeyboardInterrupt:
            pass
        finally:
            graph.stop()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
