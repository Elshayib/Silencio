"""Small Windows Core Audio adapter; endpoint IDs survive device reordering.

All instances belong to the thread that creates them. PolicyConfig is the
Windows desktop interface also used by EarTrumpet; keep it behind this seam
because it is not a public, versioned Windows SDK contract.
"""
from __future__ import annotations

import ctypes as ct
import os
import uuid
from dataclasses import dataclass
from typing import Any


class GUID(ct.Structure):
    _fields_ = [("data", ct.c_ubyte * 16)]

    def __init__(self, value: str) -> None:
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


class PropertyKey(ct.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ct.c_ulong)]


class PropVariant(ct.Structure):
    _fields_ = [("vt", ct.c_ushort), ("reserved", ct.c_ushort * 3),
                ("value", ct.c_void_p), ("extra", ct.c_void_p)]


def _call(pointer: Any, slot: int, *types: Any) -> Any:
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(ct.c_long, ct.c_void_p, *types)(table[slot])


def _check(result: int) -> None:
    if result < 0:
        raise OSError(f"Windows audio error 0x{result & 0xffffffff:08X}")


def _release(pointer: Any) -> None:
    if pointer:
        _call(pointer, 2)(pointer)


@dataclass(frozen=True)
class Endpoint:
    id: str
    name: str

    @property
    def is_cable(self) -> bool:
        # Only the bundled standard VB-CABLE; never grab another virtual rig.
        name = self.name.casefold()
        return "vb-audio virtual cable" in name and "cable" in name

    @property
    def is_virtual(self) -> bool:
        return any(word in self.name.casefold() for word in
                   ("cable", "voicemeeter", "virtual", "vb-audio", "silencio"))


class WindowsAudio:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Silencio desktop requires Windows 10 or 11 (64-bit).")
        self._ole = ct.WinDLL("ole32")
        initialized = self._ole.CoInitializeEx(None, 0)
        self._owns_com = initialized >= 0
        if initialized != -2147417850:  # RPC_E_CHANGED_MODE: caller already initialized COM
            _check(initialized)
        self._enumerator = ct.c_void_p()
        try:
            _check(self._ole.CoCreateInstance(
                ct.byref(GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")), None, 1,
                ct.byref(GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")),
                ct.byref(self._enumerator)))
        except Exception:
            if self._owns_com:
                self._ole.CoUninitialize()
            raise

    def close(self) -> None:
        _release(self._enumerator)
        self._enumerator = ct.c_void_p()
        if self._owns_com:
            self._ole.CoUninitialize()
            self._owns_com = False

    def _endpoint(self, device: Any) -> Endpoint:
        identifier = ct.c_void_p()
        _check(_call(device, 5, ct.c_void_p)(device, ct.byref(identifier)))
        try:
            endpoint_id = ct.wstring_at(identifier)
        finally:
            self._ole.CoTaskMemFree(identifier)
        store = ct.c_void_p()
        _check(_call(device, 4, ct.c_ulong, ct.c_void_p)(device, 0, ct.byref(store)))
        value = PropVariant()
        try:
            key = PropertyKey(GUID("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)
            _check(_call(store, 5, ct.c_void_p, ct.c_void_p)(store, ct.byref(key), ct.byref(value)))
            if value.vt != 31 or not value.value:
                raise RuntimeError("Windows did not provide an audio device name.")
            return Endpoint(endpoint_id, ct.wstring_at(value.value))
        finally:
            self._ole.PropVariantClear(ct.byref(value))
            _release(store)

    def endpoints(self, flow: int = 0, states: int = 1) -> list[Endpoint]:
        collection = ct.c_void_p()
        _check(_call(self._enumerator, 3, ct.c_int, ct.c_ulong, ct.c_void_p)(
            self._enumerator, flow, states, ct.byref(collection)))
        try:
            count = ct.c_uint()
            _check(_call(collection, 3, ct.c_void_p)(collection, ct.byref(count)))
            result = []
            for index in range(count.value):
                device = ct.c_void_p()
                _check(_call(collection, 4, ct.c_uint, ct.c_void_p)(collection, index, ct.byref(device)))
                try:
                    result.append(self._endpoint(device))
                finally:
                    _release(device)
            return result
        finally:
            _release(collection)

    def default(self, role: int = 0, flow: int = 0) -> str | None:
        device = ct.c_void_p()
        result = _call(self._enumerator, 4, ct.c_int, ct.c_int, ct.c_void_p)(
            self._enumerator, flow, role, ct.byref(device))
        if result == -2147023728:  # E_NOTFOUND: no connected endpoint
            return None
        _check(result)
        try:
            return self._endpoint(device).id
        finally:
            _release(device)

    def set_default(self, endpoint_id: str, role: int) -> None:
        policy = ct.c_void_p()
        _check(self._ole.CoCreateInstance(
            ct.byref(GUID("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")), None, 1,
            ct.byref(GUID("F8679F50-850A-41CF-9C72-430F290290C8")), ct.byref(policy)))
        try:
            _check(_call(policy, 13, ct.c_wchar_p, ct.c_int)(policy, endpoint_id, role))
        finally:
            _release(policy)

    def endpoint_volume(self, endpoint_id: str) -> EndpointVolume:
        """Open a thread-owned control; callers must close it before COM."""
        device = ct.c_void_p()
        _check(_call(self._enumerator, 5, ct.c_wchar_p, ct.c_void_p)(
            self._enumerator, endpoint_id, ct.byref(device)))
        pointer = ct.c_void_p()
        try:
            _check(_call(device, 3, ct.c_void_p, ct.c_ulong, ct.c_void_p, ct.c_void_p)(
                device, ct.byref(GUID("5CDF2C82-841E-4546-9722-0CF74078229A")),
                23, None, ct.byref(pointer)))
        finally:
            _release(device)
        return EndpointVolume(pointer)


@dataclass(frozen=True)
class VolumeState:
    level: float
    muted: bool


class EndpointVolume:
    """IAudioEndpointVolume, using Windows' own audio-tapered slider curve."""

    def __init__(self, pointer: Any) -> None:
        self._pointer = pointer

    def read(self) -> VolumeState:
        level = ct.c_float()
        muted = ct.c_int()
        _check(_call(self._pointer, 9, ct.c_void_p)(self._pointer, ct.byref(level)))
        _check(_call(self._pointer, 15, ct.c_void_p)(self._pointer, ct.byref(muted)))
        return VolumeState(float(level.value), bool(muted.value))

    def set_level(self, level: float) -> None:
        if not 0.0 <= level <= 1.0:
            raise ValueError("Volume must be between 0 and 1")
        _check(_call(self._pointer, 7, ct.c_float, ct.c_void_p)(self._pointer, level, None))

    def set_mute(self, muted: bool) -> None:
        _check(_call(self._pointer, 14, ct.c_int, ct.c_void_p)(self._pointer, bool(muted), None))

    def close(self) -> None:
        _release(self._pointer)
        self._pointer = ct.c_void_p()


def portaudio_index(endpoint: Endpoint, *, capture: bool = False) -> int:
    import sounddevice as sd

    apis = sd.query_hostapis()
    channels = "max_input_channels" if capture else "max_output_channels"
    matches = [index for index, device in enumerate(sd.query_devices())
               if "wasapi" in str(apis[device["hostapi"]]["name"]).lower()
               and device["name"] == endpoint.name and device[channels] >= 2]
    if len(matches) != 1:
        raise RuntimeError(f"Cannot uniquely open {endpoint.name}. Reconnect it and select Retry.")
    return matches[0]


def refresh_portaudio() -> None:
    """Call only after closing every stream in this process."""
    import sounddevice as sd

    sd._terminate()
    sd._initialize()
