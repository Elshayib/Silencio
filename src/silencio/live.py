"""Live Vocal filtering integration (ticket 03).

Thin wiring around the single engine buffer seam: mixed stereo PCM block
in, Vocal-plus-SFX stereo PCM block out. The live engine plugs the
ticket 02 :class:`CausalSeparator` into :class:`SilencioEngine` so toggle
ON emits Vocal plus SFX with Music reduced across any playback source
(browser, movie, game, song), while toggle OFF restores the original mix
bit-perfect with unity gain on the Vocal path.

Scope per ADR-0003: speaker-output render path only; microphone capture
devices are never opened or processed. Teammate speech counts only as it
arrives over speakers (Vocal). All processing is local-only; this module
performs no network I/O.

The seam contract stays stereo 48kHz (see ``resample.py`` for the 44.1kHz
adapter); WASAPI loopback, tray, hotkey, and device-change survival stay
manual per the spec because virtual audio devices are flaky under
automation.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from silencio.engine import SAMPLE_RATE, SilencioEngine
from silencio.resample import SUPPORTED_RATES, resample_stereo
from silencio.separator import LATENCY_SAMPLES, CausalSeparator
from silencio.state import ToggleStateStore

Float32Stereo = NDArray[np.float32]

_MIC_PATTERN = re.compile(r"\bmicrophone\b|\bmic\b|array|line[\s-]?in|\bcapture\b", re.IGNORECASE)


def build_live_engine(
    state_store: ToggleStateStore | None = None,
    state_path: Path | str | None = None,
    ramp_samples: int = 480,
) -> SilencioEngine:
    """Build the live filtering engine: separator wired into the seam.

    Toggle OFF is bit-perfect passthrough; toggle ON runs the causal
    separator. Either an explicit ``state_store`` or a ``state_path``
    (persisted toggle) may be given; both omitted means start OFF.
    """
    store = state_store
    if store is None and state_path is not None:
        store = ToggleStateStore(state_path)
    return SilencioEngine(
        processor=CausalSeparator(sample_rate=SAMPLE_RATE),
        state_store=store,
        sample_rate=SAMPLE_RATE,
        ramp_samples=ramp_samples,
    )


def estimate_end_to_end_ms(block_frames: int = 1024, ramp_samples: int = 480) -> float:
    """Conservative end-to-end delay estimate in milliseconds.

    Formula: two device blocks (capture plus render double-buffering) plus
    the separator pipeline latency plus the gapless toggle ramp, all at
    48kHz. Defaults: 2*1024 + 1024 + 480 = 3552 frames = 74.0ms, inside
    the 150ms budget with headroom for driver jitter. Ticket 04 proves
    the measured number with a soak; this keeps 03 honest about the sum
    of its parts.
    """
    total = 2 * int(block_frames) + int(LATENCY_SAMPLES) + int(ramp_samples)
    return float(total) / float(SAMPLE_RATE) * 1000.0


def ensure_output_only_input(device: int | str | None) -> bool:
    """Guard the render-path-only scope (ADR-0003): reject mic-like inputs.

    The live graph captures the virtual-cable loopback (speaker output),
    never a microphone capture device; teammate speech is in scope only
    as it arrives over speakers (Vocal). ``None`` (default cable) passes;
    integer PortAudio indices pass only because they cannot be classified
    without opening the device — first-run setup (ticket 05) must select
    the cable loopback, never a capture endpoint. Strings matching
    microphone/capture patterns raise :class:`ValueError` with guidance.
    """
    if device is None or isinstance(device, int):
        return True
    name = str(device)
    if _MIC_PATTERN.search(name):
        raise ValueError(
            f"refusing microphone-like input {name!r}: the live path captures "
            "the virtual-cable loopback (speaker output) only; microphone "
            "inputs are never processed (ADR-0003)."
        )
    return True


def resample_source_to_pipeline(
    block: NDArray[np.generic],
    src_rate: int,
) -> Float32Stereo:
    """Resample a 44.1kHz source block up to the 48kHz pipeline rate.

    The seam contract stays stereo 48kHz; live capture runs at the 48kHz
    device rate (the Windows mixer resamples app output before loopback),
    and this helper covers file-based 44.1kHz material on the input path.
    48kHz input returns an exact copy; anything outside
    ``SUPPORTED_RATES`` raises with setup guidance.
    """
    if src_rate not in SUPPORTED_RATES:
        raise ValueError(f"v1 input rates are {SUPPORTED_RATES}, got {src_rate}")
    arr = np.asarray(block)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"expected stereo block (frames, 2), got shape {arr.shape}")
    if src_rate == SAMPLE_RATE:
        return np.array(arr, dtype=np.float32, copy=True)
    return resample_stereo(arr, src_rate, SAMPLE_RATE)
