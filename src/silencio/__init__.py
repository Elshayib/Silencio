"""Silencio public package."""

from silencio.boost import (
    CPU_DEPTH,
    GPU_DEPTH,
    accelerator_available,
    build_boosted_live_engine,
    describe_accelerator,
)
from silencio.capture import BLOCKED_MESSAGE, BlockedCaptureMonitor, format_blocked_message
from silencio.engine import SilencioEngine
from silencio.live import (
    build_live_engine,
    ensure_output_only_input,
    estimate_end_to_end_ms,
    resample_source_to_pipeline,
)
from silencio.resample import StreamingResampler, resample_stereo
from silencio.separator import CausalSeparator
from silencio.setup import KNOWN_LIMITATIONS, SetupPlan, SetupStep, build_setup_plan, format_setup_plan
from silencio.soak import SoakConfig, SoakReport, format_soak_report, run_soak
from silencio.startup import format_startup_status, is_auto_start_enabled, set_auto_start, startup_entry_path
from silencio.state import ToggleStateStore

__all__ = [
    "BLOCKED_MESSAGE",
    "CPU_DEPTH",
    "KNOWN_LIMITATIONS",
    "BlockedCaptureMonitor",
    "CausalSeparator",
    "GPU_DEPTH",
    "SetupPlan",
    "SetupStep",
    "SilencioEngine",
    "SoakConfig",
    "SoakReport",
    "StreamingResampler",
    "ToggleStateStore",
    "accelerator_available",
    "build_boosted_live_engine",
    "build_live_engine",
    "build_setup_plan",
    "describe_accelerator",
    "ensure_output_only_input",
    "estimate_end_to_end_ms",
    "format_blocked_message",
    "format_setup_plan",
    "format_soak_report",
    "format_startup_status",
    "is_auto_start_enabled",
    "resample_source_to_pipeline",
    "resample_stereo",
    "run_soak",
    "set_auto_start",
    "startup_entry_path",
]
