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
-   ``--input-device`` / ``--output-device`` pin PortAudio devices by index
-   or name substring (defaults = system defaults; use --list-devices).
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


def _auto_cable_input() -> int | None:
    """Auto-detect the cable loopback capture device index, if present.

    Prefers WASAPI with separate capture/render streams and shared-mode
    rate conversion, then DirectSound and MME.
    Returns None when sounddevice is missing or no cable is installed.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return None
    try:
        devices = sd.query_devices()
        try:
            apis = sd.query_hostapis()
        except Exception:
            apis = []
    except Exception:
        return None
    api_name: dict[int, str] = {}
    for i, api in enumerate(apis):
        try:
            api_name[i] = str(api.get("name", "")).lower()
        except Exception:
            continue

    def rank(idx: int) -> tuple[int, int]:
        name = api_name.get(int(devices[idx].get("hostapi", -1)), "")
        if "wasapi" in name:
            return (0, idx)
        if "directsound" in name:
            return (1, idx)
        if "mme" in name:
            return (2, idx)
        return (3, idx)

    from silencio.setup import _CABLE_PATTERNS

    candidates: list[int] = []
    for idx, dev in enumerate(devices):
        try:
            name = str(dev.get("name", ""))
            ins = int(dev.get("max_input_channels", 0))
        except Exception:
            continue
        if ins >= 2 and any(token in name.lower() for token in _CABLE_PATTERNS):
            candidates.append(idx)
    if not candidates:
        return None
    candidates.sort(key=rank)
    return candidates[0]


def _auto_output_same_api(input_idx: int) -> int | None:
    """Pick an output on the same host API as the input (duplex requirement).

    PortAudio duplex streams reject cross-API pairs (PaError -9993), so the
    output must live on the same host API as the resolved input. Prefers
    the system default output when it qualifies, else a speakers-like
    endpoint, else the first output on that API.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return None
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    from silencio.setup import _CABLE_PATTERNS

    def _is_cable(name: str) -> bool:
        lowered = name.lower()
        return any(token in lowered for token in _CABLE_PATTERNS)

    try:
        host = int(devices[int(input_idx)].get("hostapi", -1))
    except Exception:
        return None
    try:
        default_out = sd.default.device[1]
        if (
            default_out is not None
            and int(default_out) >= 0
            and int(devices[int(default_out)].get("hostapi", -2)) == host
            and int(devices[int(default_out)].get("max_output_channels", 0)) >= 2
            and not _is_cable(str(devices[int(default_out)].get("name", "")))
        ):
            return int(default_out)
    except Exception:
        pass
    fallback: int | None = None
    for idx, dev in enumerate(devices):
        try:
            same = int(dev.get("hostapi", -1)) == host
            outs = int(dev.get("max_output_channels", 0))
            name = str(dev.get("name", "")).lower()
        except Exception:
            continue
        if not (same and outs >= 2):
            continue
        if _is_cable(name):
            continue
        if fallback is None:
            fallback = idx
        if "speaker" in name or "realtek" in name or "headphone" in name:
            return idx
    return fallback


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
    from silencio.capture import BLOCKED_MESSAGE
    from silencio.graph import build_engine
    from silencio.startup import format_startup_status, is_auto_start_enabled, startup_entry_path

    engine = build_engine(state_path)
    entry = startup_entry if startup_entry is not None else startup_entry_path()
    print(f"toggle={'ON' if engine.enabled else 'OFF'} persisted to {state_path}")
    from silencio.runtime import read_runtime
    health = read_runtime(state_path)
    if health is None or not health.get("running"):
        print("live filter: NOT RUNNING; saved ON does not start audio. Use --run --on.")
    else:
        print(f"live filter: RUNNING (pid {health['pid']}, profile {health.get('profile')})")
        print(f"capture: {health.get('capture_status')}; latency estimate: {health.get('latency_ms')}ms")
    print(format_startup_status(is_auto_start_enabled(entry), entry))
    if health is not None and health.get("running"):
        print(f"backend: {health.get('backend', 'unknown')}")
        print(f"processing: {health.get('processing_ms', 0):.2f}ms average; {health.get('max_processing_ms', 0):.2f}ms peak; deadline misses: {health.get('deadline_misses', 0)}")
        print(f"underruns: {health.get('underruns', 0)}; overruns: {health.get('overruns', 0)}; error: {health.get('error')}")
    else:
        print("backend: selected when the live filter starts")
    print("latency target: 150ms including devices, processing and bounded buffers")
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
    parser.add_argument("--profile", choices=("speech", "speech-quality", "speech-fast", "aggressive", "balanced"), default="speech", help="speech: laptop dialogue; speech-quality: heavier model; speech-fast: lowest CPU; aggressive/balanced: legacy filters")
    parser.add_argument("--speech-strength", type=float, default=2.0, help="speech-fast only: 1..3; larger values cut more residual Music")
    parser.add_argument("--soak-seconds", type=float, default=30.0)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--setup", action="store_true", help="ticket 05 guided first-run setup")
    parser.add_argument("--diagnose", action="store_true", help="ticket 05 toggle/startup/latency report")
    parser.add_argument("--install-startup", action="store_true", help="enable auto-start on login")
    parser.add_argument("--remove-startup", action="store_true", help="disable auto-start on login")
    parser.add_argument("--startup-path", type=Path, default=None)
    parser.add_argument("--run", action="store_true", help="start live graph")
    parser.add_argument("--tray", action="store_true", help="show Music toggle and Quit in the Windows tray")
    parser.add_argument("--input-device", default=None, help="PortAudio input (index or name substring); default = cable loopback")
    parser.add_argument("--output-device", default=None, help="PortAudio output (index or name substring); default = system default")
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
    if args.on and args.off:
        parser.error("choose either --on or --off")
    if (args.on or args.off) and not args.run:
        engine = build_engine(state_path)
        engine.set_enabled(bool(args.on))
        print(f"toggle={'ON' if engine.enabled else 'OFF'} persisted to {state_path}")
        return 0
    if args.run:
        from silencio.boost import build_boosted_live_engine
        from silencio.graph import start_tray, unregister_hotkey
        from silencio.runtime import LiveInstance, write_runtime
        from threading import Event

        if args.backend not in ("auto", "cpu", "gpu"):
            print(f'backend must be "auto", "cpu" or "gpu", got {args.backend!r}', file=sys.stderr)
            return 2

        def _device(value: str | None) -> int | str | None:
            if value is None:
                return None
            try:
                return int(value)
            except ValueError:
                return value

        try:
            engine = build_boosted_live_engine(state_path=state_path, prefer=args.backend,
                profile=args.profile, speech_strength=args.speech_strength,
                enabled=bool(args.on) if (args.on or args.off) else None)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        input_device = _device(args.input_device)
        if input_device is None:
            auto = _auto_cable_input()
            if auto is not None:
                input_device = auto
                print(f"auto input: cable loopback device {auto}")
            else:
                print("no virtual cable found; install VB-Cable and use --list-devices.", file=sys.stderr)
                return 2
        output_device = _device(args.output_device)
        if output_device is None and isinstance(input_device, int):
            same_api = _auto_output_same_api(input_device)
            if same_api is not None:
                output_device = same_api
                print(f"auto output: same-API device {same_api}")
        try:
            graph = AudioGraph(
                engine,
                GraphConfig(
                    block_frames=480,
                    input_device=input_device,
                    output_device=output_device,
                ),
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"starting live Vocal filter (toggle={'ON' if engine.enabled else 'OFF'})")
        print(f"backend: {engine.backend_name}")
        print("ON: spoken Vocal with Music suppressed; OFF: original mix bit-perfect." if args.profile.startswith("speech") else "ON: spectral Music suppression; OFF: original mix bit-perfect.")
        print(f"latency estimate: {graph.latency_estimate_ms:.1f}ms (budget 150ms)")
        print("local-only: no audio leaves this machine; mic inputs never processed.")
        print(f"profile: {args.profile}; no separator can guarantee zero Music on every mix.")
        print("Setup: virtual output = Default Playback, exclusive-mode off,")
        print("input = cable loopback (never a microphone), output = real speakers.")
        instance = LiveInstance(state_path)
        if not instance.acquire():
            print("Silencio is already running; use --on, --off, --toggle or Ctrl+Alt+M.", file=sys.stderr)
            return 2
        hotkey_handle = register_hotkey(graph.toggle)
        if hotkey_handle is None:
            print("hotkey: Ctrl+Alt+M unavailable (pip install .[tray]); use --toggle in another shell.")
        else:
            print("hotkey: Ctrl+Alt+M toggles live.")
        # The manual CLI uses the same final-device volume link as the desktop.
        # Other host APIs retain their own mixer behavior.
        volume_audio = None
        volume_link = None
        def close_volume() -> None:
            try:
                if volume_link is not None:
                    volume_link.close()
            finally:
                if volume_audio is not None:
                    volume_audio.close()
        try:
            import os
            import sounddevice as sd
            output_info = sd.query_devices(output_device, "output")
            if os.name == "nt" and "wasapi" in str(sd.query_hostapis()[output_info['hostapi']]['name']).lower():
                from silencio.windows_audio import WindowsAudio
                from silencio.volume import VolumeLink
                volume_audio = WindowsAudio()
                endpoints = volume_audio.endpoints()
                cable = next(device for device in endpoints if device.is_cable)
                speakers = next(device for device in endpoints if device.name == output_info['name'] and not device.is_virtual)
                volume_link = VolumeLink(volume_audio, cable.id, speakers.id, graph.set_output_muted,
                    cable_is_default=volume_audio.default() == cable.id)
            graph.start()
        except RuntimeError as exc:
            close_volume()
            instance.close()
            unregister_hotkey(hotkey_handle)
            print(str(exc), file=sys.stderr)
            return 2
        except Exception as exc:
            close_volume()
            instance.close()
            unregister_hotkey(hotkey_handle)
            print(f"could not open audio stream: {exc}", file=sys.stderr)
            print("hint: set CABLE Input as Default Playback at 48000Hz, or", file=sys.stderr)
            print("pass explicit devices, e.g. --input-device 8 --output-device 10.", file=sys.stderr)
            return 2
        print("running; Ctrl+C to stop.")
        print(f"device latency plus processing/buffering: {graph.latency_estimate_ms:.1f}ms (driver reported)")
        quit_requested = Event()
        tray = start_tray(graph.toggle, quit_requested.set, lambda: engine.enabled) if args.tray else None
        try:
            import time

            last_capture = None
            last_error = None
            status_at = 0.0
            while not quit_requested.is_set():
                time.sleep(0.05)
                if volume_link is not None:
                    volume_link.poll()
                if time.monotonic() < status_at:
                    continue
                status_at = time.monotonic() + .5
                if graph.poll():
                    print(f"toggle={'ON' if engine.enabled else 'OFF'} (external control)")
                    if tray is not None:
                        tray.update_menu()
                write_runtime(state_path, dict(running=graph.is_running, enabled=engine.enabled,
                    profile=args.profile, backend=engine.backend_name, input_device=input_device, output_device=output_device,
                    capture_status=graph.capture_status, captured_frames=graph.captured_frames,
                    input_rms=graph.input_rms, output_rms=graph.output_rms,
                    latency_ms=round(graph.latency_estimate_ms, 1), underruns=graph.underruns,
                    overruns=graph.overruns, error=graph.last_error,
                    processing_ms=round(graph.processing_ms, 3),
                    max_processing_ms=round(graph.max_processing_ms, 3),
                    deadline_misses=graph.processing_deadline_misses))
                if graph.capture_status != last_capture:
                    from silencio.capture import format_blocked_message
                    print(format_blocked_message(graph.capture_status))
                    last_capture = graph.capture_status
                if graph.last_error and graph.last_error != last_error:
                    print(f"audio processing error: {graph.last_error}", file=sys.stderr)
                    last_error = graph.last_error
        except KeyboardInterrupt:
            pass
        finally:
            try:
                if volume_link is not None:
                    volume_link.poll()
            finally:
                try:
                    graph.stop()
                    write_runtime(state_path, dict(running=False, enabled=engine.enabled, profile=args.profile))
                finally:
                    close_volume()
                    if tray is not None:
                        tray.stop()
                    unregister_hotkey(hotkey_handle)
                    instance.close()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
