"""Transactional playback routing with a durable crash-recovery journal."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Protocol

from silencio.state import replace_with_retry
from silencio.windows_audio import Endpoint, VolumeState
from silencio.volume import VolumeControl


class AudioSystem(Protocol):
    def endpoints(self, flow: int = 0, states: int = 1) -> list[Endpoint]: ...
    def default(self, role: int = 0, flow: int = 0) -> str | None: ...
    def set_default(self, endpoint_id: str, role: int) -> None: ...
    def endpoint_volume(self, endpoint_id: str) -> VolumeControl: ...


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class RoutingLease:
    def __init__(self, system: AudioSystem, path: Path) -> None:
        self.system = system
        self.path = path
        self._volume: VolumeState | None = None

    def activate(self, cable: Endpoint, speakers: Endpoint, volume: VolumeState | None = None) -> None:
        if not cable.is_cable or speakers.is_virtual:
            raise ValueError("Routing needs VB-CABLE and a physical playback device.")
        if self.path.exists():
            raise RuntimeError("Previous sound routing must be restored before starting.")
        original = {str(role): self.system.default(role) for role in range(3)}
        # A driver installation (or a previous manual setup) may already have
        # selected the cable. Never restore a dead cable when we exit.
        original = {role: speakers.id if value == cable.id or value is None else value
                    for role, value in original.items()}
        data: dict[str, object] = {"cable": cable.id, "fallback": speakers.id, "original": original}
        if volume is not None:
            data['volume'] = {'level': volume.level, 'muted': volume.muted}
        save_json(self.path, data)
        self._volume = volume
        try:
            for role in range(3):
                self.system.set_default(cable.id, role)
        except Exception:
            self.restore()
            raise

    def remember_volume(self, volume: VolumeState) -> None:
        """Persist only changes, so a guardian/fallback preserves mute too."""
        if volume == self._volume or not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['volume'] = {'level': volume.level, 'muted': volume.muted}
        save_json(self.path, data)
        self._volume = volume

    def restore(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        active = {device.id for device in self.system.endpoints() if not device.is_virtual}
        fallback = data["fallback"] if data["fallback"] in active else next(iter(sorted(active)), None)
        pending = False
        volume = data.get('volume')
        restored: set[str] = set()
        for role in range(3):
            # Respect a user's explicit change while Silencio was running.
            if self.system.default(role) != data["cable"]:
                continue
            target = data["original"][str(role)]
            if target not in active:
                target = fallback
            if target is None:
                pending = True
                continue
            if volume is not None and target not in restored:
                control = self.system.endpoint_volume(target)
                try:
                    # Silence first: restoring a different physical device
                    # must not expose its previously saved loud/unmuted level.
                    control.set_mute(True)
                    control.set_level(float(volume['level']))
                    control.set_mute(bool(volume['muted']) or float(volume['level']) == 0)
                finally:
                    control.close()
                restored.add(target)
            self.system.set_default(target, role)
        if not pending:
            self.path.unlink(missing_ok=True)
