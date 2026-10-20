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
from time import perf_counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from silencio.capture import BlockedCaptureMonitor, CaptureStatus
from silencio.engine import NUM_CHANNELS, SAMPLE_RATE, SilencioEngine
from silencio.live import ensure_output_only_input
from silencio.state import ToggleStateStore
from silencio.resample import DEVICE_RATES, BandlimitedResampler
from silencio.playback import PlaybackBridge


class _StreamPair:
    """Independent WASAPI clocks with a bounded bridge, never unbounded lag."""

    def __init__(self, capture: Any, render: Any) -> None:
        self.capture = capture
        self.render = render

    @property
    def active(self) -> bool:
        return bool(self.capture.active and self.render.active)

    @property
    def latency(self) -> tuple[float, float]:
        return float(self.capture.latency), float(self.render.latency)

    def start(self) -> None:
        self.capture.start()
        self.render.start()

    def stop(self) -> None:
        try:
            self.capture.stop()
        finally:
            self.render.stop()

    def close(self) -> None:
        try:
            self.capture.close()
        finally:
            self.render.close()


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
        if cfg.block_frames < 1:
            raise ValueError("block_frames must be positive")
        # Render-path-only scope (ADR-0003): fail fast on mic-like inputs
        # before any block flows, and keep the live delay inside budget.
        ensure_output_only_input(cfg.input_device)
        budget_ms = (2 * cfg.block_frames + engine.latency_samples + engine.ramp_samples) / SAMPLE_RATE * 1000
        if budget_ms > 150.0:
            raise ValueError(
                f"block_frames={cfg.block_frames} estimates {budget_ms:.1f}ms "
                "end-to-end, over the 150ms budget; use a smaller block."
            )
        self._engine = engine
        self._config = cfg
        self._running = False
        self._output_muted = False
        self._reopen_needed = False
        self._stream: Any = None
        self.last_error: str | None = None
        self.captured_frames = 0
        self.input_rms = 0.0
        self.output_rms = 0.0
        self.underruns = 0
        self.overruns = 0
        self.processing_ms = 0.0
        self.max_processing_ms = 0.0
        self.processing_deadline_misses = 0
        self._conversion_delay_ms = 0.0
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
        if self._stream is not None:
            capture, render = self._stream.latency
            bridge = 4 * self._config.block_frames if isinstance(self._stream, _StreamPair) else 0
            processing_delay = self._engine.latency_samples if self._engine.enabled else 0
            return (float(capture) + float(render) + (processing_delay + bridge) / SAMPLE_RATE) * 1000 + self._conversion_delay_ms
        return (2 * self._config.block_frames + self._engine.latency_samples + self._engine.ramp_samples) / SAMPLE_RATE * 1000

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

    def set_output_muted(self, muted: bool) -> None:
        """Final render gate, independent of ON/OFF and already queued audio."""
        self._output_muted = bool(muted)

    def _gate_output(self, outdata: np.ndarray) -> None:
        if self._output_muted:
            outdata.fill(0)

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
        if not self._running:
            self._engine.reset_for_device_change()
        self._capture.reset()
        self._reopen_needed = True

    def reopen(self) -> None:
        if self._running:
            self._restart_stream()
        else:
            self._reopen_needed = False

    def poll(self) -> bool:
        """Refresh external controls and detect a stopped PortAudio callback."""
        changed = self._engine.reload_state()
        if self._running and self._stream is not None:
            try:
                self._reopen_needed = self._reopen_needed or not self._stream.active
            except Exception:
                self._reopen_needed = True
        if self._reopen_needed:
            self._restart_stream()
        return changed

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
        # Resolve numeric/default devices too; guarding only a user-supplied
        # name silently allowed microphone capture and feedback into the cable.
        from silencio.setup import _CABLE_PATTERNS
        input_info = sd.query_devices(cfg.input_device, "input")
        output_info = sd.query_devices(cfg.output_device, "output")
        input_name = str(input_info["name"])
        output_name = str(output_info["name"])
        ensure_output_only_input(input_name)
        if not any(token in input_name.lower() for token in _CABLE_PATTERNS):
            raise ValueError("input must be the virtual cable output, never a microphone")
        if any(token in output_name.lower() for token in _CABLE_PATTERNS):
            raise ValueError("feedback route refused: output must be real speakers, not the virtual cable")
        if int(input_info["max_input_channels"]) < NUM_CHANNELS:
            raise ValueError("virtual cable input must support stereo")
        if int(output_info["max_output_channels"]) < NUM_CHANNELS:
            raise ValueError("real speakers must support stereo")
        if input_info["hostapi"] != output_info["hostapi"]:
            raise ValueError("input and output must use the same host API; use --list-devices")

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
            if mixed.shape != (frames, NUM_CHANNELS):
                self.last_error = "audio driver returned an invalid stereo block"
                outdata.fill(0)
                return
            # Blocked-capture reporting (ticket 05): silent loopback from
            # DRM-protected or exclusive-mode sources is a known
            # limitation, never a crash; observe and keep rendering.
            outdata[:] = self._process_audio(mixed)
            self._gate_output(outdata)

        api = sd.query_hostapis()[int(input_info["hostapi"])]
        self._conversion_delay_ms = 0.0
        if "wasapi" in str(api["name"]).lower():
            # Duplex WASAPI cannot span different endpoints. Separate shared
            # streams can. Use native rates with explicit conversion: forcing
            # 48kHz capture on a 44.1kHz cable can deliver audio too slowly.
            input_rate = int(input_info["default_samplerate"])
            output_rate = int(output_info["default_samplerate"])
            if input_rate not in DEVICE_RATES or output_rate not in DEVICE_RATES:
                raise ValueError("unsupported device format; choose 44.1, 48, 88.2, 96, 176.4 or 192 kHz in Windows Sound")
            input_frames = round(cfg.block_frames * input_rate / SAMPLE_RATE)
            output_frames = round(cfg.block_frames * output_rate / SAMPLE_RATE)
            to_pipeline = BandlimitedResampler(input_rate, SAMPLE_RATE)
            to_speakers = BandlimitedResampler(SAMPLE_RATE, output_rate)
            self._conversion_delay_ms = (to_pipeline.delay_seconds + to_speakers.delay_seconds) * 1000
            bridge = PlaybackBridge(output_frames, output_rate)

            def process_captured(indata: np.ndarray) -> None:
                converted = to_pipeline.push(indata)
                if len(converted) == 0:
                    return
                out = to_speakers.push(self._process_audio(converted))
                if len(out) == 0:
                    return
                previous_overruns = bridge.overruns
                bridge.push(out)
                self.overruns += bridge.overruns - previous_overruns

            def capture_callback(indata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
                if status:
                    self.overruns += 1
                try:
                    process_captured(indata)
                except Exception as exc:
                    self.last_error = str(exc)
                    self._reopen_needed = True

            def render_callback(outdata: np.ndarray, frames: int, _time: Any, status: Any) -> None:
                if status:
                    self.underruns += 1
                previous_underruns = bridge.underruns
                bridge.render(outdata)
                self._gate_output(outdata)
                self.underruns += bridge.underruns - previous_underruns

            options = dict(channels=NUM_CHANNELS, dtype="float32", latency=0.01)
            capture = sd.InputStream(device=cfg.input_device, callback=capture_callback,
                samplerate=input_rate, blocksize=input_frames, **options)
            try:
                render = sd.OutputStream(device=cfg.output_device, callback=render_callback,
                    samplerate=output_rate, blocksize=output_frames, **options)
            except Exception:
                capture.close()
                raise
            stream = _StreamPair(capture, render)
        else:
            stream = sd.Stream(
                samplerate=SAMPLE_RATE, channels=NUM_CHANNELS,
                dtype="float32", blocksize=cfg.block_frames, latency="low",
                callback=callback, device=(cfg.input_device, cfg.output_device),
            )
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream
        self._running = True
        self._reopen_needed = False

    def _process_audio(self, mixed: np.ndarray) -> np.ndarray:
        self.observe_input(mixed)
        started = perf_counter()
        try:
            out = self._engine.process_block(mixed)
            if not np.all(np.isfinite(out)):
                raise ValueError("processor emitted non-finite audio")
            self.captured_frames += len(mixed)
            self.input_rms = float(np.sqrt(np.mean(mixed * mixed)))
            self.output_rms = float(np.sqrt(np.mean(out * out)))
            return out
        except Exception as exc:
            self.last_error = str(exc)
            self._reopen_needed = True
            # Keep the callback alive; never leak the original Music mix on
            # a DSP exception. The control loop reports the error.
            return np.zeros_like(mixed)
        finally:
            elapsed_ms = (perf_counter() - started) * 1000
            self.processing_ms += .02 * (elapsed_ms - self.processing_ms)
            self.max_processing_ms = max(self.max_processing_ms, elapsed_ms)
            if elapsed_ms > len(mixed) / SAMPLE_RATE * 1000:
                self.processing_deadline_misses += 1

    def stop(self) -> None:
        try:
            if self._stream is not None:
                try:
                    self._stream.stop()
                finally:
                    self._stream.close()
        finally:
            self._stream = None
            self._running = False
            self._reopen_needed = False

    def _restart_stream(self) -> None:
        if self._stream is not None:
            try:
                try:
                    self._stream.stop()
                finally:
                    self._stream.close()
            except Exception as exc:
                self.last_error = str(exc)
            finally:
                self._stream = None
        # Re-create on next start(); flag cleared by reopen().
        self._running = False
        try:
            self._engine.reset_for_device_change()
            self._capture.reset()
            self.start()
        except Exception as exc:
            # No audio backend in CI/offline: stay stopped but armed so the
            # next start() after replug still recovers without a restart.
            print(f"audio backend unavailable, graph armed for reopen: {exc}")
            self._reopen_needed = True


def build_engine(state_path: Path | None = None, ramp_samples: int = 480) -> SilencioEngine:
    store = ToggleStateStore(state_path if state_path is not None else default_state_path())
    return SilencioEngine(state_store=store, ramp_samples=ramp_samples)


def register_hotkey(on_toggle: Any, hotkey: str = "ctrl+alt+m") -> Any:
    """Register a global hotkey; returns a handle or None when unavailable."""
    try:
        import keyboard
    except ImportError:
        return None
    try:
        return keyboard.add_hotkey(hotkey, lambda: on_toggle())
    except Exception:
        return None


def unregister_hotkey(handle: Any) -> None:
    if handle is not None:
        try:
            import keyboard
            keyboard.remove_hotkey(handle)
        except Exception:
            pass


def start_tray(on_toggle: Any, on_quit: Any, is_enabled: Any) -> Any:
    """Nonblocking tray controls for the live control loop."""
    try:
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (64, 64), (30, 30, 30))
        draw = ImageDraw.Draw(image)
        draw.ellipse([8, 8, 56, 56], fill=(0, 200, 120))
        icon = pystray.Icon("Silencio", image, "Silencio — Music suppression")

        def toggle(_icon: Any, _item: Any) -> None:
            on_toggle()
            icon.update_menu()

        icon.menu = pystray.Menu(
            pystray.MenuItem("Suppress Music", toggle, checked=lambda _: bool(is_enabled())),
            pystray.MenuItem("Quit", lambda _icon, _item: on_quit()),
        )
        icon.run_detached()
        return icon
    except Exception as exc:
        print(f"tray unavailable: {exc}; Ctrl+Alt+M still controls filtering")
        return None


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
