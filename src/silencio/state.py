"""Persisted global toggle state.

The toggle must survive restarts (ticket 01 checklist). Storage is a tiny
JSON file so the engine seam stays free of OS-specific registry APIs.
"""

from __future__ import annotations

import json
from pathlib import Path


class ToggleStateStore:
    """Load/save the global ON/OFF flag as JSON ``{"enabled": bool}``."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> bool:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return False
        try:
            data = json.loads(raw)
        except ValueError:
            return False
        if isinstance(data, dict):
            enabled = data.get("enabled", False)
            return bool(enabled) if isinstance(enabled, bool) else False
        return False

    def save(self, enabled: bool) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"enabled": bool(enabled)})
        self._path.write_text(payload, encoding="utf-8")
