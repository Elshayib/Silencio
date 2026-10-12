"""Live audio graph: virtual-cable loopback -> engine -> real speakers.

Thin adapter over the tested :class:`SilencioEngine` seam. Deliberately kept
free of DSP logic so automated tests stay at the buffer seam; WASAPI
loopback, tray, hotkey, and device-change survival are verified manually via
live AB per the spec (virtual audio devices are flaky under automation).

Chain per ADR-0001: a virtual output (VB-Cable/VoiceMeeter style) becomes
Default Playback, this tool captures its loopback, runs
``SilencioEngine.process_block``, and renders to the real speakers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from silencio.capture import BlockedCaptureMonitor, CaptureStatus
from silencio.engine import NUM_CHANNELS, SAMPLE_RATE, SilencioEngine
from silencio.live import ensure_output_only_input, estimate_end_to_end_ms
from silencio.state import ToggleStateStore


def default_state_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Silencio" / "state.json"
    return Path.home() / ".config" / "silencio" / "state.json"


@dataclass
class GraphConfig:
    block_frames: int = 1024
    input_device: int | str | None = None
    output_device: int | str | None = None


class AudioGraph:
    """Owns the loopback capture -> engine -> render path."""

    def __init__(
        self,
        engine: SilencioEngine,
        config: GraphConfig | None = None,
        capture_monitor: BlockedCaptureMonitor | None = None,
    ) -> None:
        cfg = config if config is not None else GraphConfig()
        # Render-path-only scope (ADR-0003): fail fast on mic-like inputs
        # before any block flows, and keep the live delay inside budget.
        ensure_output_only_input(cfg.input_device)
        budget_ms = estimate_end_to_end_ms(
            block_frames=cfg.block_frames, ramp_samples=engine.ramp_samples
        )
        if budget_ms > 150.0:
            raise ValueError(
                f"block_frames={cfg.block_frames} estimates {budget_ms:.1f}ms "
                "end-to-end, over the 150ms budget; use a smaller block."
            )
        self._engine = engine
        self._config = cfg
        self._running = False
        self._reopen_needed = False
        self._stream: Any = None
        self._capture = capture_monitor if capture_monitor is not None else BlockedCaptureMonitor()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def needs_reopen(self) -> bool:
        return self._reopen_needed

    @property
    def engine(self) -> SilencioEngine:
        return self._engine

    @property
    def latency_estimate_ms(self) -> float:
        return estimate_end_to_end_ms(
            block_frames=self._config.block_frames,
            ramp_samples=self._engine.ramp_samples,
        )

    @property
    def capture_status(self) -> CaptureStatus:
        return self._capture.status

    def observe_input(self, block: np.ndarray) -> CaptureStatus:
        """Observe one captured input block for blocked-capture reporting.

        Defensive: never raises on malformed driver blocks; the live path
        must keep rendering instead of crashing on a known limitation.
        """
        try:
            return self._capture.push(block)
        except Exception:
            return self._capture.status

    def set_enabled(self, on: bool) -> None:
        self._engine.set_enabled(bool(on))

    def toggle(self) -> bool:
        self._engine.set_enabled(not self._engine.enabled)
        return self._engine.enabled

    def on_device_change(self) -> None:
        """Headphone unplug/replug or default-device switch: no restart.

        Keeps the persisted toggle, drops the mid-ramp transient, and flags
        the stream for reopen. The caller (or the MMNotification hook)
        should call :meth:`reopen` next; if the graph is not running the
        flag simply arms the next :meth:`start`.
        """
        self._engine.reset_for_device_change()
        self._capture.reset()
        self._reopen_needed = True

    def reopen(self) -> None:
        self._reopen_needed = False
        if self._running:
            self._restart_stream()

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is not installed (pip install silencio[audio]); "
                "offline engine checks still run without it."
            ) from exc
        ensure_output_only_input(self._config.input_device)
        if self._running:
            return
        cfg = self._config

        def callback(
            indata: np.ndarray, outdata: np.ndarray, frames: int, _time: Any, status: Any
        ) -> None:
            # Input is the device-rate 48kHz loopback by construction (the
            # stream opens at SAMPLE_RATE, so the Windows mixer has already
            # resampled 44.1kHz app output before capture); file-based
            # 44.1kHz material converts via resample_source_to_pipeline.
            if status:
                # Dropout logged by PortAudio; keep rendering to avoid a gap.
                pass
            mixed = np.asarray(indata, dtype=np.float32)
            if mixed.shape[0] != frames or mixed.shape[1] != NUM_CHANNELS:
                # Driver shape bug: prefer the untouched mix (no loss) over
                # silence when it still fits the output buffer.
                try:
                    outdata[:] = np.asarray(indata, dtype=np.float32)[:frames, :NUM_CHANNELS]
                except ValueError:
                    outdata[:] = np.zeros_like(outdata)
                return
            # Blocked-capture reporting (ticket 05): silent loopback from
            # DRM-protected or exclusive-mode sources is a known
            # limitation, never a crash; observe and keep rendering.
            self.observe_input(mixed)
            out = self._engine.process_block(mixed)
            outdata[:] = out

        self._stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            channels=NUM_CHANNELS,
            dtype="float32",
            blocksize=cfg.block_frames,
            callback=callback,
            device=(cfg.input_device, cfg.output_device),
        )
        self._stream.start()
        self._running = True
        self._reopen_needed = False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        self._running = False

    def _restart_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        # Re-create on next start(); flag cleared by reopen().
        self._running = False
        try:
            self.start()
        except RuntimeError as exc:
            # No audio backend in CI/offline: stay stopped but armed so the
            # next start() after replug still recovers without a restart.
            print(f"audio backend unavailable, graph armed for reopen: {exc}")


def build_engine(state_path: Path | None = None, ramp_samples: int = 480) -> SilencioEngine:
    store = ToggleStateStore(state_path if state_path is not None else default_state_path())
    return SilencioEngine(state_store=store, ramp_samples=ramp_samples)


def register_hotkey(on_toggle: Any, hotkey: str = "ctrl+alt+m") -> Any:
    """Register a global hotkey; returns a handle or None when unavailable."""
    try:
        import keyboard
    except ImportError:
        return None
    return keyboard.add_hotkey(hotkey, lambda: on_toggle())


def run_tray(on_toggle: Any, on_quit: Any) -> None:
    """Blocking tray loop; no-op with a warning when pystray is missing."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("pystray/Pillow not installed; running without tray icon.")
        try:
            while True:
                input("Press Enter to toggle, Ctrl+C to quit...\n")
                on_toggle()
        except KeyboardInterrupt:
            on_quit()
        return

    image = Image.new("RGB", (64, 64), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    draw.ellipse([8, 8, 56, 56], fill=(0, 200, 120))

    def _toggle(icon: Any, _item: Any) -> None:
        on_toggle()

    def _quit(icon: Any, _item: Any) -> None:
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Toggle Silencio", _toggle),
        pystray.MenuItem("Quit", _quit),
    )
    icon = pystray.Icon("Silencio", image, "Silencio", menu)
    icon.run()
