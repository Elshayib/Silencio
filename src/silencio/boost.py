"""Optional GPU boost for the live Vocal filter (ticket 04).

The compute floor stays CPU-only on a mid-range quad-core (ADR-0002):
the ticket 02 causal separator runs gapless on CPU alone and the ticket
04 soak proves it. When a GPU is present this module selects a deeper
residue-reduction pass behind the *same* engine buffer seam — mixed
stereo PCM in, Vocal-plus-SFX stereo PCM out — with identical toggle
semantics (OFF bit-perfect, switch under 50ms, persisted state).

No heavy dependency is required: detection probes guarded optional
imports (``torch.cuda``, ``onnxruntime`` GPU providers) plus an explicit
``SILENCIO_FORCE_GPU=1`` override for offline/CI exercise. When no GPU
is present, ``prefer="auto"`` returns the standard CPU engine so the
toggle workflow never changes; ``prefer="gpu"`` forces the deeper pass
so the equal-or-cleaner property stays testable without hardware.
"""

from __future__ import annotations

import os
from pathlib import Path

from silencio.engine import SAMPLE_RATE, SilencioEngine
from silencio.separator import CausalSeparator
from silencio.state import ToggleStateStore

CPU_DEPTH: float = 0.75
GPU_DEPTH: float = 0.85


def accelerator_available() -> bool:
    """Report whether a GPU residue-reducer is usable on this machine."""
    if os.environ.get("SILENCIO_FORCE_GPU", "").strip() == "1":
        return True
    try:
        import torch

        cuda = getattr(getattr(torch, "cuda", None), "is_available", None)
        if callable(cuda) and bool(cuda()):
            return True
    except ImportError:
        pass
    except Exception:
        pass
    try:
        import onnxruntime as ort

        get_providers: object = getattr(ort, "get_available_providers", lambda: [])
        names: list[str] = [str(p) for p in list(get_providers())]  # type: ignore[operator]
        if any("CUDA" in p or "Dml" in p or "GPU" in p for p in names):
            return True
    except ImportError:
        pass
    except Exception:
        pass
    return False


def describe_accelerator() -> str:
    """Human-readable backend name: ``"gpu"`` when usable, else ``"cpu"``."""
    return "gpu" if accelerator_available() else "cpu"


def build_boosted_live_engine(
    state_store: ToggleStateStore | None = None,
    state_path: Path | str | None = None,
    ramp_samples: int = 480,
    prefer: str = "auto",
    enabled: bool | None = None,
) -> SilencioEngine:
    """Build the live engine, boosting residue reduction on GPU hardware.

    ``prefer="auto"`` uses the deeper pass only when
    :func:`accelerator_available` holds, otherwise the standard CPU
    separator; ``prefer="cpu"`` always uses the CPU pass;
    ``prefer="gpu"`` always uses the deeper pass (offline simulation of
    GPU-present hardware). ``enabled=True`` starts ON, ``False`` starts
    OFF, ``None`` (default) restores the persisted toggle or OFF.
    """
    if prefer not in ("auto", "cpu", "gpu"):
        raise ValueError(f'prefer must be "auto", "cpu" or "gpu", got {prefer!r}')
    use_boost = prefer == "gpu" or (prefer == "auto" and accelerator_available())
    depth = GPU_DEPTH if use_boost else CPU_DEPTH
    store = state_store
    if store is None and state_path is not None:
        store = ToggleStateStore(state_path)
    engine = SilencioEngine(
        processor=CausalSeparator(sample_rate=SAMPLE_RATE, music_depth=depth),
        state_store=store,
        sample_rate=SAMPLE_RATE,
        ramp_samples=ramp_samples,
    )
    if enabled is not None:
        engine.set_enabled(bool(enabled))
    return engine
