"""One worker owns audio, COM, preferences, and routing; UI uses messages."""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

from silencio.boost import build_boosted_live_engine
from silencio.desktop_support import PROFILES, Preferences
from silencio.driver import driver_installed, install_driver, reboot_pending
from silencio.graph import AudioGraph, GraphConfig
from silencio.routing import RoutingLease
from silencio.runtime import write_runtime
from silencio.state import ToggleStateStore
from silencio.windows_audio import Endpoint, VolumeState, WindowsAudio, portaudio_index, refresh_portaudio
from silencio.volume import VolumeLink


class DesktopRuntime(threading.Thread):
    def __init__(self, state_path: Path, preferences: Preferences, *, first_run: bool = False) -> None:
        super().__init__(name="Silencio audio", daemon=True)
        self.state_path = state_path
        self.preferences = preferences
        self.first_run = first_run
        self.commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.graph: AudioGraph | None = None
        self.audio: WindowsAudio | None = None
        self.route: RoutingLease | None = None
        self.output: Endpoint | None = None
        self.input_index: int | None = None
        self.output_index: int | None = None
        self.volume: VolumeLink | None = None
        self._volume_state: VolumeState | None = None
        self._last_frames = 0
        self._last_progress = time.monotonic()

    def send(self, action: str, value: Any = None) -> None:
        self.commands.put((action, value))

    def report(self, title: str, detail: str, **extra: Any) -> None:
        self.events.put(dict(title=title, detail=detail, **extra))

    def stop_audio(self) -> None:
        try:
            if self.volume:
                self.volume.poll()
                self._volume_state = self.volume.state
                if self.route:
                    self.route.remember_volume(self.volume.state)
        finally:
            self._close_audio()

    def _close_audio(self) -> None:
        try:
            if self.route:
                self.route.restore()
        finally:
            try:
                if self.graph:
                    self.graph.stop()
                    self.graph = None
            finally:
                if self.volume:
                    self.volume.close()
                    self.volume = None
                write_runtime(self.state_path, {"running": False})

    def devices(self) -> tuple[list[Endpoint], Endpoint | None, Endpoint | None]:
        assert self.audio is not None
        outputs = self.audio.endpoints()
        physical = [device for device in outputs if not device.is_virtual]
        cable = next((device for device in outputs if device.is_cable), None)
        capture = next((device for device in self.audio.endpoints(1) if device.is_cable), None)
        self.events.put({"outputs": [(device.id, device.name) for device in physical]})
        return physical, cable, capture

    def start_audio(self) -> bool:
        assert self.audio is not None and self.route is not None
        self.route.restore()
        marker = self.state_path.with_suffix(".restart.json")
        if reboot_pending(marker):
            self.report("Restart Windows to finish", "The audio driver is installed. Silencio will start automatically after your next sign-in.",
                        running=False, restart=True)
            return False
        physical, cable, capture = self.devices()
        if cable is None or capture is None:
            # A disabled/partly installed device must not be reinstalled: the
            # vendor setup could otherwise turn an install into an uninstall.
            installed = driver_installed() or any(device.is_cable for device in self.audio.endpoints(states=15))
            if installed:
                self.report("Audio device unavailable", "Enable VB-CABLE in Windows Sound, or restart Windows, then select Retry.", running=False)
            else:
                self.report("Set up system audio", "Silencio includes the audio driver. Windows will ask for administrator permission once.",
                            running=False, driver=True)
                if self.first_run:
                    self.first_run = False
                    self.setup_driver()
            return False
        if not physical:
            self.report("Connect speakers or headphones", "Silencio will reconnect automatically when a playback device is available.", running=False)
            return False
        default = self.audio.default()
        self.output = next((device for device in physical if device.id == self.preferences.output_id), None)
        if self.output is None:
            self.output = next((device for device in physical if device.id == default), physical[0])
        self.report("Preparing your audio", "Loading the local Vocal filter…", running=False)
        refresh_portaudio()
        store = ToggleStateStore(self.state_path)
        enabled = store.read_enabled()
        engine = build_boosted_live_engine(state_path=self.state_path, prefer="cpu",
            profile=self.preferences.profile, enabled=True if enabled is None else enabled)
        self.input_index = portaudio_index(capture, capture=True)
        self.output_index = portaudio_index(self.output)
        graph = AudioGraph(engine, GraphConfig(block_frames=480,
            input_device=self.input_index, output_device=self.output_index))
        try:
            self.volume = VolumeLink(self.audio, cable.id, self.output.id,
                graph.set_output_muted, cable_is_default=default == cable.id,
                initial_state=self._volume_state)
            graph.start()
            # Only redirect applications after both audio streams have opened.
            self.route.activate(cable, self.output, self.volume.state)
        except Exception:
            try:
                graph.stop()
            finally:
                if self.volume:
                    self.volume.close()
                    self.volume = None
            raise
        self.graph = graph
        self._last_frames = 0
        self._last_progress = time.monotonic()
        self.events.put({"selected_output": self.output.id})
        logging.info("Started %s on %s", self.preferences.profile, self.output.name)
        return True

    def setup_driver(self) -> None:
        assert self.audio is not None
        self.report("Installing the audio driver", "Approve the Windows permission prompt. Setup may take a minute.", running=False, busy=True)
        install_driver(self.audio, self.state_path.with_suffix(".restart.json"))
        self.report("Restart Windows to finish", "The audio driver is installed. Silencio will start automatically after your next sign-in.",
                    running=False, restart=True)

    def run(self) -> None:
        retry_at = 0.0
        devices_at = 0.0
        status_at = 0.0
        try:
            self.audio = WindowsAudio()
            self.route = RoutingLease(self.audio, self.state_path.with_suffix(".routing.json"))
            self.route.restore()
            while True:
                try:
                    action, value = self.commands.get(timeout=.05)
                except queue.Empty:
                    action, value = "", None
                if action == "quit":
                    break
                try:
                    if action == "toggle":
                        if self.graph:
                            self.graph.toggle()
                    elif action in ("profile", "output", "retry"):
                        if action == "profile" and value in PROFILES.values():
                            self.preferences.profile = value
                        if action == "output":
                            self.preferences.output_id = str(value)
                        self.preferences.save(self.state_path.with_suffix(".preferences.json"))
                        self.stop_audio()
                        retry_at = 0
                    elif action == "driver":
                        if not driver_installed() and not any(device.is_cable for device in self.audio.endpoints(states=15)):
                            self.setup_driver()
                        retry_at = time.monotonic() + 5
                    if self.graph is None and time.monotonic() >= retry_at:
                        self.start_audio()
                        retry_at = time.monotonic() + 5
                    if self.graph:
                        graph = self.graph
                        if self.volume:
                            self.volume.poll()
                            self._volume_state = self.volume.state
                            self.route.remember_volume(self.volume.state)
                        graph.engine.reload_state()
                        if graph.last_error or graph.needs_reopen:
                            raise RuntimeError(graph.last_error or "The audio connection was interrupted.")
                        # poll() also detects inactive streams; the desktop owns
                        # the subsequent device selection and route recovery.
                        graph.poll()
                        if not graph.is_running or graph.last_error:
                            raise RuntimeError(graph.last_error or "The audio connection was interrupted.")
                        if graph.captured_frames != self._last_frames:
                            self._last_frames = graph.captured_frames
                            self._last_progress = time.monotonic()
                        elif time.monotonic() - self._last_progress > 5:
                            raise RuntimeError("The audio device stopped responding. Reconnecting…")
                        if time.monotonic() >= devices_at:
                            physical, cable, capture = self.devices()
                            devices_at = time.monotonic() + 2
                            if self.output not in physical or cable is None or capture is None:
                                raise RuntimeError("Audio devices changed. Reconnecting…")
                            default = self.audio.default()
                            if default != cable.id:
                                selected = next((device for device in physical if device.id == default), None)
                                if selected:
                                    self.preferences.output_id = selected.id
                                    self.stop_audio()
                                    retry_at = 0
                                    continue
                        if time.monotonic() < status_at:
                            continue
                        status_at = time.monotonic() + .25
                        status = dict(running=True, enabled=graph.engine.enabled, profile=self.preferences.profile,
                            input_device=self.input_index, output_device=self.output_index,
                            backend=graph.engine.backend_name, capture_status=graph.capture_status,
                            captured_frames=graph.captured_frames, input_rms=graph.input_rms, output_rms=graph.output_rms,
                            latency_ms=round(graph.latency_estimate_ms, 1), processing_ms=round(graph.processing_ms, 2),
                            max_processing_ms=round(graph.max_processing_ms, 2), deadline_misses=graph.processing_deadline_misses,
                            underruns=graph.underruns, overruns=graph.overruns, error=graph.last_error)
                        if self.volume:
                            status.update(volume_level=self.volume.state.level,
                                          muted=self.volume.state.muted or self.volume.state.level == 0)
                        write_runtime(self.state_path, status)
                        self.report("Music suppression is on" if graph.engine.enabled else "Original audio is playing",
                            "Play something in your browser, player, or game." if graph.input_rms == 0 else
                            "Spoken Vocal, with less background Music." if graph.engine.enabled else
                            "Switch on whenever you want less Music.", **status)
                except Exception as exc:
                    logging.exception("Audio operation failed")
                    try:
                        self.stop_audio()
                    except Exception:
                        logging.exception("Could not restore the sound route")
                    self.report("Audio needs attention", str(exc), running=False, error=True)
                    retry_at = time.monotonic() + 10
        except Exception as exc:
            logging.exception("Desktop audio worker failed")
            self.report("Could not start Silencio", str(exc), running=False, error=True)
        finally:
            try:
                self.stop_audio()
            except Exception:
                logging.exception("Shutdown route restoration failed; journal retained")
            if self.audio:
                self.audio.close()
            self.events.put({"stopped": True})
