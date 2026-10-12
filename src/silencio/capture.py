"""Blocked-capture reporting for ticket 05 (offline, no hardware).

Loopback capture can go silent when a source blocks it (DRM-protected
apps) or bypasses the virtual output (exclusive-mode). Per the spec
those are known limitations, never failures: this monitor watches the
captured input blocks and reports sustained silence honestly instead
of crashing. It observes only; the engine seam still decides what the
listener hears.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray

CaptureStatus = Literal["ok", "silent", "blocked-suspected"]

BLOCKED_MESSAGE: str = (
    "Capture is silent: playback may be paused, or the source blocks "
    "loopback capture (DRM-protected apps go silent; exclusive-mode apps "
    "bypass the virtual output). Recorded as a known limitation, not a "
    "failure: check exclusive-mode is off, the virtual output is Default "
    "Playback, and restart the app. The tool keeps running."
)


class BlockedCaptureMonitor:
    """Count consecutive silent input blocks; flag sustained silence.

    A block is silent when its peak absolute sample falls below
    ``silence_threshold``. The first quiet blocks report ``"silent"``
    (paused playback); once ``blocks_to_flag`` consecutive silent blocks
    accumulate the monitor reports ``"blocked-suspected"`` with honest
    guidance. Any sounding block resets the count to ``"ok"``.
    """

    def __init__(
        self,
        silence_threshold: float = 1e-4,
        blocks_to_flag: int = 94,
    ) -> None:
        if not silence_threshold > 0.0:
            raise ValueError(f"silence_threshold must be positive, got {silence_threshold}")
        if blocks_to_flag < 1:
            raise ValueError(f"blocks_to_flag must be >= 1, got {blocks_to_flag}")
        self._threshold = float(silence_threshold)
        self._blocks_to_flag = int(blocks_to_flag)
        self._silent_blocks = 0
        self._status: CaptureStatus = "ok"

    @property
    def status(self) -> CaptureStatus:
        return self._status

    @property
    def silent_blocks(self) -> int:
        return self._silent_blocks

    def reset(self) -> None:
        """Drop silence history (device-change recovery without restart)."""
        self._silent_blocks = 0
        self._status = "ok"

    def push(self, block: NDArray[np.generic]) -> CaptureStatus:
        """Observe one stereo input block; returns the current status."""
        arr = np.asarray(block)
        if arr.ndim != 2 or arr.shape[1] != 2:
            raise ValueError(f"expected stereo block (frames, 2), got shape {arr.shape}")
        if arr.shape[0] == 0:
            raise ValueError("expected non-empty block")
        peak = float(np.max(np.abs(arr.astype(np.float64))))
        if peak >= self._threshold:
            self._silent_blocks = 0
            self._status = "ok"
            return self._status
        self._silent_blocks += 1
        if self._silent_blocks >= self._blocks_to_flag:
            self._status = "blocked-suspected"
        else:
            self._status = "silent"
        return self._status


def format_blocked_message(status: CaptureStatus) -> str:
    """Render honest guidance for a capture status (never a crash)."""
    if status == "ok":
        return "Capture OK: loopback input carries playback."
    if status == "silent":
        return (
            "Capture silent: playback may be paused. If playback runs and "
            "capture stays silent, see the blocked-capture guidance."
        )
    return BLOCKED_MESSAGE
