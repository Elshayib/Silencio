"""Auto-start plus persisted-toggle startup behaviour (ticket 05, offline).

The toggle itself persists via :class:`ToggleStateStore`; this module owns
the "tool starts automatically" half: a Windows Startup-folder launcher
that runs the live graph on login. All paths are file operations only,
so guidance stays testable without elevation or WASAPI hardware.
"""

from __future__ import annotations

import os
from pathlib import Path

ENTRY_FILENAME: str = "Silencio.bat"
DEFAULT_TARGET: str = "python -m silencio --run"


def startup_entry_path(base: Path | str | None = None) -> Path:
    """Resolve the auto-start launcher path.

    ``base`` overrides the directory (tests); otherwise Windows uses the
    per-user Startup folder and other OSes fall back to
    ``~/.config/silencio/startup``.
    """
    if base is not None:
        return Path(base) / ENTRY_FILENAME
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / ENTRY_FILENAME
        )
    return Path.home() / ".config" / "silencio" / "startup" / ENTRY_FILENAME


def is_auto_start_enabled(entry: Path | str | None = None) -> bool:
    """Report whether the auto-start launcher exists."""
    path = Path(entry) if entry is not None else startup_entry_path()
    return path.is_file()


def set_auto_start(
    enabled: bool,
    entry: Path | str | None = None,
    target: str = DEFAULT_TARGET,
) -> Path:
    """Create or remove the auto-start launcher; returns its path."""
    path = Path(entry) if entry is not None else startup_entry_path()
    if not bool(enabled):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return Path(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    launcher = f"@echo off\r\nrem Silencio auto-start (ticket 05): live Vocal filter on login.\r\n{target}\r\n"
    Path(path).write_text(launcher, encoding="utf-8")
    return Path(path)


def format_startup_status(enabled: bool, path: Path | str) -> str:
    """Render one-line auto-start status for --setup output."""
    state = "ON" if bool(enabled) else "OFF"
    return f"auto-start: {state} ({Path(path)})"
