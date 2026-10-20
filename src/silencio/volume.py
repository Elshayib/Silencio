"""Link the default cable's Windows controls to the physical render endpoint.

VB-CABLE can ignore endpoint volume; attenuation belongs on the real speakers,
after separation. COM and polling stay on the control thread, never a callback.
"""
from __future__ import annotations

from typing import Callable, Protocol

from silencio.windows_audio import VolumeState


class VolumeControl(Protocol):
    def read(self) -> VolumeState: ...
    def set_level(self, level: float) -> None: ...
    def set_mute(self, muted: bool) -> None: ...
    def close(self) -> None: ...


class VolumeSystem(Protocol):
    def endpoint_volume(self, endpoint_id: str) -> VolumeControl: ...


def _changed(first: VolumeState, second: VolumeState) -> bool:
    return abs(first.level - second.level) > 1e-4 or first.muted != second.muted


def _write(control: VolumeControl, state: VolumeState) -> None:
    current = control.read()
    # Mute before changing level; unmute only after the new level is in place.
    if state.muted and not current.muted:
        control.set_mute(True)
    if abs(current.level - state.level) > 1e-4:
        control.set_level(state.level)
    if not state.muted and current.muted:
        control.set_mute(False)


class VolumeLink:
    def __init__(self, system: VolumeSystem, cable_id: str, output_id: str,
                 set_output_muted: Callable[[bool], None], *, cable_is_default: bool,
                 initial_state: VolumeState | None = None) -> None:
        self._set_output_muted = set_output_muted
        self._cable = system.endpoint_volume(cable_id)
        try:
            self._output = system.endpoint_volume(output_id)
        except Exception:
            self._cable.close()
            raise
        try:
            # A new route inherits the speakers' level, including mute. An
            # existing cable default already represents the user's intention.
            state = initial_state if initial_state is not None else (
                self._cable.read() if cable_is_default else self._output.read())
            self._apply(state)
        except Exception:
            self.close()
            raise

    def _apply(self, state: VolumeState) -> None:
        silent = state.muted or state.level == 0.0
        if silent:
            self._set_output_muted(True)
        _write(self._cable, state)
        _write(self._output, VolumeState(state.level, silent))
        self._last_cable = self._cable.read()
        self._last_output = self._output.read()
        self.state = state
        self._set_output_muted(silent)

    def poll(self) -> None:
        try:
            cable, output = self._cable.read(), self._output.read()
            # Default Windows control wins simultaneous changes. Read back
            # hardware-quantized levels so our own writes never bounce back.
            if _changed(cable, self._last_cable):
                self._apply(cable)
            elif _changed(output, self._last_output):
                self._apply(output)
        except Exception:
            self._set_output_muted(True)
            raise

    def close(self) -> None:
        try:
            self._cable.close()
        finally:
            self._output.close()
