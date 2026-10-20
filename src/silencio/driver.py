"""Install the bundled, unmodified VB-CABLE package on first launch only."""
from __future__ import annotations

import ctypes as ct
import hashlib
import json
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

from silencio.routing import save_json
from silencio.windows_audio import WindowsAudio


def driver_directory() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "vendor" / "vbcable" if getattr(sys, "frozen", False) else root / "packaging" / "vendor" / "vbcable"


def driver_installed() -> bool:
    """Device labels can be renamed or disabled; use the vendor's service ID."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services\VBAudioVACMME"):
            return True
    except FileNotFoundError:
        return False


def boot_time() -> float:
    kernel = ct.WinDLL("kernel32")
    kernel.GetTickCount64.restype = ct.c_ulonglong
    return time.time() - float(kernel.GetTickCount64()) / 1000


def reboot_pending(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return abs(float(data["boot_time"]) - boot_time()) < 120
    except (OSError, ValueError, KeyError, TypeError):
        return False


class ShellExecuteInfo(ct.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.ULONG), ("hwnd", wt.HWND),
                ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR),
                ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR),
                ("nShow", ct.c_int), ("hInstApp", wt.HINSTANCE),
                ("lpIDList", ct.c_void_p), ("lpClass", wt.LPCWSTR),
                ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD),
                ("hIcon", wt.HANDLE), ("hProcess", wt.HANDLE)]


def install_driver(audio: WindowsAudio, restart_marker: Path) -> None:
    if driver_installed():
        raise RuntimeError("VB-CABLE is already installed. Enable its devices or restart Windows, then select Retry.")
    directory = driver_directory()
    manifest = directory.parent / "vbcable-manifest.json"
    hashes = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    # Verify every packaged file before passing any of them to an elevated tool.
    for filename, expected in hashes.items():
        if Path(filename).name != filename:
            raise RuntimeError("Invalid driver package manifest.")
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != expected:
            raise RuntimeError("The audio driver package is damaged. Reinstall Silencio.")
    executable = directory / "VBCABLE_Setup_x64.exe"
    original = {(flow, role): audio.default(role, flow) for flow in range(2) for role in range(3)}
    info = ShellExecuteInfo()
    info.cbSize = ct.sizeof(info)
    info.fMask = 0x40 | 0x100  # process handle + do not show shell error UI
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = "-i -h"
    info.lpDirectory = str(directory)
    info.nShow = 0
    shell = ct.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ct.POINTER(ShellExecuteInfo)]
    if not shell.ShellExecuteExW(ct.byref(info)):
        if ct.get_last_error() == 1223:
            raise RuntimeError("Windows permission was declined. Select Set up audio to try again.")
        raise ct.WinError(ct.get_last_error())
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    try:
        # Driver install must finish; never terminate an in-flight driver update.
        kernel.WaitForSingleObject(info.hProcess, 0xffffffff)
        code = wt.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ct.byref(code)):
            raise ct.WinError(ct.get_last_error())
    finally:
        kernel.CloseHandle(info.hProcess)
        # Installing a new driver can replace both playback AND recording defaults.
        # Restore the user's microphone without ever opening or recording it.
        for (flow, role), endpoint_id in original.items():
            active = {endpoint.id for endpoint in audio.endpoints(flow)}
            current = audio.default(role, flow)
            cables = {endpoint.id for endpoint in audio.endpoints(flow) if endpoint.is_cable}
            if endpoint_id in active and current in cables:
                audio.set_default(endpoint_id, role)
    installed = any(endpoint.is_cable for endpoint in audio.endpoints(states=15))
    if code.value not in (0, 3010) and not installed:
        raise RuntimeError(f"Windows could not install the audio driver (code {code.value}). Restart Windows and retry.")
    save_json(restart_marker, {"boot_time": boot_time()})
