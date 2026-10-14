"""Ticket 01 acceptance at the single engine buffer seam.

Seam: mixed stereo PCM block in -> Vocal-plus-SFX stereo PCM block out,
via SilencioEngine.process_block() + set_enabled() + persisted state.
Live WASAPI/tray/hotkey/device-driver behaviour is manual per spec, not automated.

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.
"""

from pathlib import Path

import numpy as np
import pytest

from silencio.engine import MAX_SWITCH_SAMPLES_50MS, SAMPLE_RATE, SilencioEngine
from silencio.state import ToggleStateStore


def _sine_stereo(frames: int, freq_l: float = 440.0, freq_r: float = 550.0) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / float(SAMPLE_RATE)
    left = (0.5 * np.sin(2.0 * np.pi * freq_l * t)).astype(np.float32)
    right = (0.5 * np.sin(2.0 * np.pi * freq_r * t)).astype(np.float32)
    return np.stack([left, right], axis=1)


def test_off_passthrough_is_bit_perfect() -> None:
    engine = SilencioEngine()
    assert engine.enabled is False
    mixed = _sine_stereo(4800)
    out = engine.process_block(mixed)
    assert out.shape == mixed.shape
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out, mixed)


def test_on_passthrough_is_bit_perfect_for_ticket_01() -> None:
    # Ticket 01 has no separation yet: ON still emits the mix untouched
    # (loudness parity, gain 1.0) so the toggle path can be proven gapless.
    engine = SilencioEngine()
    engine.set_enabled(True)
    # Drain the <50ms ramp so we observe steady-state ON.
    drain = np.zeros((4096, 2), dtype=np.float32)
    engine.process_block(drain)
    mixed = _sine_stereo(4800)
    out = engine.process_block(mixed)
    np.testing.assert_array_equal(out, mixed)


def test_toggle_completes_within_50ms() -> None:
    # Fake future separator: silence. Proves the ramp machinery finishes
    # inside the 50ms budget even when ON and OFF paths differ.
    engine = SilencioEngine(processor=lambda m: np.zeros_like(m))
    engine.set_enabled(True)
    total = 0
    # Feed small blocks until output is fully processed (all zeros for sine in).
    probe = _sine_stereo(256)
    for _ in range(32):
        out = engine.process_block(probe)
        total += probe.shape[0]
        if np.max(np.abs(out)) == 0.0:
            break
    assert total <= MAX_SWITCH_SAMPLES_50MS


def test_toggle_produces_no_pop_or_click() -> None:
    # Worst case for a click: instant full-scale drop. A linear crossfade
    # keeps per-sample steps near the natural sine slope; an instant switch
    # would jump by up to 0.5 in one sample.
    engine = SilencioEngine(
        processor=lambda m: np.zeros_like(m), ramp_samples=480
    )
    steady = _sine_stereo(4800)
    # Natural slope of the 440Hz/550Hz 0.5-amplitude probe (independent truth).
    natural = float(np.max(np.abs(np.diff(steady, axis=0))))
    assert natural < 0.06

    engine.set_enabled(True)
    outputs: list[np.ndarray] = []
    # Continuous 960-sample stream in 120-sample slices preserves phase, so
    # any discontinuity comes only from the crossfade, not block boundaries.
    stream_in = _sine_stereo(960)
    for start in range(0, 960, 120):
        outputs.append(engine.process_block(stream_in[start : start + 120]))
    stream = np.concatenate(outputs, axis=0)
    step = float(np.max(np.abs(np.diff(stream, axis=0))))
    # Pop budget: natural slope plus a small ramp contribution, far below
    # the ~0.5 jump an unramped switch would produce.
    assert step < 0.06


def test_toggle_state_persists_across_restarts(tmp_path: Path) -> None:
    store = ToggleStateStore(tmp_path / "state.json")
    assert store.load() is False
    engine = SilencioEngine(state_store=store)
    engine.set_enabled(True)
    assert store.load() is True
    # A fresh engine on the same file restores ON (persisted toggle).
    revived = SilencioEngine(state_store=ToggleStateStore(tmp_path / "state.json"))
    assert revived.enabled is True
    revived.set_enabled(False)
    assert ToggleStateStore(tmp_path / "state.json").load() is False


def test_device_change_recovery_preserves_toggle_without_restart() -> None:
    engine = SilencioEngine(processor=lambda m: np.zeros_like(m))
    engine.set_enabled(True)
    engine.process_block(_sine_stereo(100))  # mid-ramp transient
    engine.reset_for_device_change()  # headphone unplug/replug: no restart
    assert engine.enabled is True
    out = engine.process_block(np.zeros((256, 2), dtype=np.float32))
    assert out.shape == (256, 2)
    # After recovery the engine still converges to the ON path.
    for _ in range(16):
        out = engine.process_block(_sine_stereo(256))
    np.testing.assert_array_equal(out, np.zeros_like(out))


def test_stereo_image_preserved_at_48k() -> None:
    assert SAMPLE_RATE == 48000
    engine = SilencioEngine()
    assert engine.sample_rate == 48000
    assert engine.num_channels == 2
    mixed = _sine_stereo(1024, freq_l=440.0, freq_r=880.0)
    assert not np.array_equal(mixed[:, 0], mixed[:, 1])
    out = engine.process_block(mixed)
    np.testing.assert_array_equal(out[:, 0], mixed[:, 0])
    np.testing.assert_array_equal(out[:, 1], mixed[:, 1])


def test_rejects_non_stereo_blocks() -> None:
    engine = SilencioEngine()
    with pytest.raises(ValueError):
        engine.process_block(np.zeros((512,), dtype=np.float32))
    with pytest.raises(ValueError):
        engine.process_block(np.zeros((512, 1), dtype=np.float32))


def test_off_suspends_model_and_resuming_clears_stale_audio():
    class Processor:
        calls = 0
        resets = 0
        def __call__(self, block):
            self.calls += 1
            return block.copy()
        def reset(self):
            self.resets += 1
    processor = Processor()
    engine = SilencioEngine(processor=processor)
    block = _sine_stereo(4800)
    for _ in range(5):
        np.testing.assert_array_equal(engine.process_block(block),block)
    assert processor.calls == 0
    engine.set_enabled(True)
    engine.process_block(block)
    assert processor.calls == processor.resets == 1
    engine.set_enabled(False)
    engine.process_block(block)
    calls = processor.calls
    for _ in range(5):
        np.testing.assert_array_equal(engine.process_block(block),block)
    assert processor.calls == calls
    engine.set_enabled(True)
    engine.process_block(block)
    assert processor.resets == 2
