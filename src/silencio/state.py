"""Persisted global toggle state.

The toggle must survive restarts (ticket 01 checklist). Storage is a tiny
JSON file so the engine seam stays free of OS-specific registry APIs.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def replace_with_retry(source: str | Path, destination: Path) -> None:
    """Windows readers briefly deny replacement; retry off the audio thread."""
    for attempt in range(4):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(.005)


class ToggleStateStore:
    """Load/save the global ON/OFF flag as JSON ``{"enabled": bool}``."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> bool:
        return self.read_enabled() is True

    def read_enabled(self) -> bool | None:
        """None means unavailable, so a live reload never turns OFF on a bad read."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if isinstance(data, dict):
            enabled = data.get("enabled")
            return enabled if isinstance(enabled, bool) else None
        return None

    def save(self, enabled: bool) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"enabled": bool(enabled)})
        # Replace atomically: the live process must never read a half-written toggle.
        fd, name = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
            replace_with_retry(name, self._path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
