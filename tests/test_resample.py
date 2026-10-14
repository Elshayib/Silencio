"""Ticket 03 input-path resampling adapter (44.1kHz sources -> 48kHz seam).

Seam: the engine buffer seam stays stereo 48kHz-only; this adapter owns
the input-path resampling on the way in. Numpy-only, CPU, deterministic,
stereo-image preserving (no mono downmix).

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.
"""

from __future__ import annotations

import numpy as np
import pytest

from silencio.resample import SUPPORTED_RATES, StreamingResampler, resample_stereo


@pytest.mark.parametrize('src,dst', [(44100,48000), (48000,44100)])
def test_live_resampling_preserves_vocal_detail_without_images(src, dst):
    from silencio.resample import BandlimitedResampler
    frames = src // 5
    t = np.arange(frames) / src
    x = np.column_stack((.3*np.sin(2*np.pi*7000*t), .2*np.sin(2*np.pi*15000*t))).astype(np.float32)
    converter = BandlimitedResampler(src,dst)
    y = np.concatenate([converter.push(x[i:i+441]) for i in range(0,len(x),441)])
    times = np.arange(len(y))/dst - converter.delay_seconds
    reference = np.column_stack((.3*np.sin(2*np.pi*7000*times),.2*np.sin(2*np.pi*15000*times)))
    error = np.mean((y[100:] - reference[100:])**2) / np.mean(reference[100:]**2)
    assert 10*np.log10(error) < -70
    other = BandlimitedResampler(src,dst)
    whole = other.push(x)
    np.testing.assert_array_equal(y,whole)


def test_live_resampling_equal_rates_is_bit_perfect():
    from silencio.resample import BandlimitedResampler
    x = _sine_44k(4410)
    converter = BandlimitedResampler(48000,48000)
    assert converter.delay_seconds == 0
    np.testing.assert_array_equal(converter.push(x),x)


def _sine_44k(frames: int, freq: float = 440.0) -> np.ndarray:
    t = np.arange(frames, dtype=np.float64) / 44100.0
    mono = (0.5 * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono * 0.5], axis=1)


def test_resample_44k_to_48k_preserves_pitch_and_stereo() -> None:
    from silencio.metrics import bandpower

    block = _sine_44k(4410)
    out = resample_stereo(block, 44100, 48000)
    assert out.shape[1] == 2
    assert out.dtype == np.float32
    # Frame count follows the rate ratio.
    assert abs(out.shape[0] - int(round(4410 * 48000 / 44100))) <= 1
    # 440Hz tone still dominates after resampling (independent FFT check).
    mono = out[:, 0] + out[:, 1]
    assert bandpower(mono, 400.0, 480.0) > bandpower(mono, 1000.0, 2000.0)
    # Stereo image survives: right stays half of left.
    assert abs(float(np.sqrt(np.mean(out[:, 1] ** 2)) / np.sqrt(np.mean(out[:, 0] ** 2))) - 0.5) < 0.05


def test_streaming_resampler_matches_whole_buffer() -> None:
    block = _sine_44k(4410)
    whole = resample_stereo(block, 44100, 48000)
    stream = StreamingResampler(44100, 48000)
    parts = [stream.push(block[i : i + 512]) for i in range(0, 4410, 512)]
    tail = stream.flush()
    got = np.concatenate(parts + [tail], axis=0) if parts else tail
    assert got.shape == whole.shape
    np.testing.assert_allclose(got, whole, atol=1e-4)


def test_resample_round_trip_stays_transparent_on_real_mixes() -> None:
    # Linear resampling is lossy full-band by construction; on real
    # bandlimited mixes the round trip must stay inaudible so the input
    # path never clips Vocal before the seam judges it.
    from silencio.clips import make_song_clip
    from silencio.metrics import db, total_power

    clip = make_song_clip()
    down = resample_stereo(clip.mix, 48000, 44100)
    round_tripped = resample_stereo(down, 44100, 48000)
    assert round_tripped.shape == clip.mix.shape
    assert abs(db(total_power(round_tripped), total_power(clip.mix))) <= 0.5
    assert float(np.max(np.abs(round_tripped.astype(np.float64) - clip.mix.astype(np.float64)))) < 0.06


def test_resample_rejects_unsupported_rates_and_mono() -> None:
    block = _sine_44k(100)
    with pytest.raises(ValueError):
        resample_stereo(block, 32000, 48000)
    with pytest.raises(ValueError):
        resample_stereo(block, 44100, 96000)
    with pytest.raises(ValueError):
        resample_stereo(np.zeros((100,), dtype=np.float32), 44100, 48000)
    assert SUPPORTED_RATES == (44100, 48000)
