"""Silencio public package."""

from silencio.boost import (
    CPU_DEPTH,
    GPU_DEPTH,
    accelerator_available,
    build_boosted_live_engine,
    describe_accelerator,
)
from silencio.engine import SilencioEngine
from silencio.live import (
    build_live_engine,
    ensure_output_only_input,
    estimate_end_to_end_ms,
    resample_source_to_pipeline,
)
from silencio.resample import StreamingResampler, resample_stereo
from silencio.separator import CausalSeparator
from silencio.soak import SoakConfig, SoakReport, format_soak_report, run_soak
from silencio.state import ToggleStateStore

__all__ = [
    "CPU_DEPTH",
    "CausalSeparator",
    "GPU_DEPTH",
    "SilencioEngine",
    "SoakConfig",
    "SoakReport",
    "StreamingResampler",
    "ToggleStateStore",
    "accelerator_available",
    "build_boosted_live_engine",
    "build_live_engine",
    "describe_accelerator",
    "ensure_output_only_input",
    "estimate_end_to_end_ms",
    "format_soak_report",
    "resample_source_to_pipeline",
    "resample_stereo",
    "run_soak",
]
