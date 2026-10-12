"""CLI entry: ``python -m silencio``.

- ``--check`` runs an offline self-check through the tested buffer seam
  (no audio hardware needed) and prints a manual-AB record.
- ``--clips`` runs the ticket 02 acceptance harness (three clips plus
  crowd/unison probes) through the same seam and prints PASS/FAIL numbers.
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
from silencio.live import build_live_engine, estimate_end_to_end_ms


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="silencio")
    parser.add_argument("--check", action="store_true", help="offline seam check")
    parser.add_argument("--clips", action="store_true", help="ticket 02 clip harness")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--run", action="store_true", help="start live graph")
    parser.add_argument("--toggle", action="store_true", help="flip persisted toggle")
    parser.add_argument("--on", action="store_true")
    parser.add_argument("--off", action="store_true")
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args(argv)

    state_path = args.state if args.state is not None else default_state_path()

    if args.check:
        return offline_check()
    if args.clips:
        report = run_acceptance()
        print(format_report(report))
        return 0 if report.passed else 1
    if args.list_devices:
        return list_devices()
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
        engine = build_live_engine(state_path=state_path)
        graph = AudioGraph(engine, GraphConfig())
        print(f"starting live Vocal filter (toggle={'ON' if engine.enabled else 'OFF'})")
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
