"""Desktop preferences, launch-at-login, and crash recovery process."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from silencio.routing import RoutingLease, save_json
from silencio.runtime import LiveInstance

PROFILES = {"Everyday": "speech", "Low CPU": "speech-fast", "Maximum suppression": "speech-quality"}
from silencio.version import VERSION as VERSION


def data_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Silencio"
    base.mkdir(parents=True, exist_ok=True)
    return base


def launch_command(*arguments: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, "-m", "silencio.desktop", *arguments]


@dataclass
class Preferences:
    profile: str = "speech"
    output_id: str = ""
    start_with_windows: bool = True

    @classmethod
    def load(cls, path: Path) -> Preferences:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                profile=data.get("profile") if data.get("profile") in PROFILES.values() else "speech",
                output_id=data.get("output_id") if isinstance(data.get("output_id"), str) else "",
                start_with_windows=data.get("start_with_windows") is not False,
            )
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        save_json(path, asdict(self))


def set_login_start(enabled: bool) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "Silencio", 0, winreg.REG_SZ,
                             subprocess.list2cmdline(launch_command("--background")))
        else:
            try:
                winreg.DeleteValue(key, "Silencio")
            except FileNotFoundError:
                pass


def start_guardian(state_path: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(launch_command("--watch", str(os.getpid()), "--state", str(state_path)),
                            creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)


def watch_parent(pid: int, state_path: Path) -> int:
    from silencio.windows_audio import WindowsAudio

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            kernel.WaitForSingleObject(handle, 0xffffffff)
        finally:
            kernel.CloseHandle(handle)
    elif ctypes.get_last_error() != 87:  # Already exited; access denied is unsafe.
        return 1
    # Serialize recovery against both a new desktop and the CLI renderer.
    instance = LiveInstance(state_path)
    if not instance.acquire():
        return 0
    try:
        audio = WindowsAudio()
        try:
            RoutingLease(audio, state_path.with_suffix(".routing.json")).restore()
        finally:
            audio.close()
    finally:
        instance.close()
    return 0


def request_existing(state_path: Path, action: str) -> None:
    if action not in ("show", "quit"):
        raise ValueError("Unknown desktop command")
    save_json(state_path.with_suffix(".command.json"), {"action": action, "at": time.time()})


def consume_command(state_path: Path) -> str | None:
    path = state_path.with_suffix(".command.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        if 0 <= time.time() - data["at"] < 15 and data["action"] in ("show", "quit"):
            return str(data["action"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def configure_logging() -> None:
    from logging.handlers import RotatingFileHandler

    log = data_directory() / "logs"
    log.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[RotatingFileHandler(log / "silencio.log", maxBytes=2_000_000,
                                      backupCount=3, encoding="utf-8")])
