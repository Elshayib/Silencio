"""Regression checks through the real streaming speech/engine boundary."""
import numpy as np
import pytest

from silencio.boost import build_boosted_live_engine
from silencio.speech import SpeechSeparator, FastSpeechSeparator, LATENCY_SAMPLES
from speech_material import instrumental, attenuation_db, recorded, si_sdr


def process(engine, x, chunk=480):
    return np.concatenate([engine.process_block(x[i:i+chunk]) for i in range(0,len(x),chunk)])


def test_centered_changing_music_is_suppressed():
    x = instrumental()
    engine = build_boosted_live_engine(profile="speech", prefer="cpu", enabled=True)
    y = process(engine, x)
    assert attenuation_db(y[48000:], x[48000:]) < -25


@pytest.mark.parametrize('factory', [SpeechSeparator, FastSpeechSeparator])
def test_speech_streaming_is_chunk_independent_and_resettable(factory):
    x = instrumental(.2)
    engine = factory()
    first = process(engine, x, 127)
    engine.reset()
    np.testing.assert_array_equal(first, process(engine, x, 2048))
    assert np.isfinite(first).all()


def test_speech_off_is_bit_perfect():
    x = instrumental(.15)
    engine = build_boosted_live_engine(profile="speech", enabled=False)
    np.testing.assert_array_equal(process(engine, x), x)


def test_speech_does_not_leak_dry_music_at_startup():
    engine = build_boosted_live_engine(profile="speech", enabled=True)
    y = engine.process_block(np.full((480,2), .2, np.float32))
    assert not np.any(y)


def test_speech_latency_is_reported_by_engine():
    engine = build_boosted_live_engine(profile="speech")
    assert engine.latency_samples == LATENCY_SAMPLES
    assert LATENCY_SAMPLES / 48000 < .065


def test_speech_does_not_cancel_opposite_phase_channels():
    x = recorded('dialogue')[:48000]
    x[:,1] *= -1
    y = process(SpeechSeparator(), x)
    assert attenuation_db(y[LATENCY_SAMPLES:], x[:-LATENCY_SAMPLES]) > -3
    assert si_sdr(y[LATENCY_SAMPLES:], x[:-LATENCY_SAMPLES]) > 8


def test_speech_input_validation_does_not_poison_recurrent_state():
    processor = SpeechSeparator()
    with pytest.raises(ValueError, match="non-finite"):
        processor(np.full((480,2), np.nan, np.float32))
    assert np.isfinite(processor(instrumental(.1))).all()


def test_speech_model_missing_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr("silencio.speech.MODEL_PATH", tmp_path / "missing.onnx")
    with pytest.raises(RuntimeError, match="missing or damaged"):
        SpeechSeparator()


def test_recorded_music_and_dialogue_through_live_engine():
    speech = recorded('dialogue')
    music = recorded('music')
    music *= np.sqrt(np.mean(speech**2) / np.mean(music**2))
    mix = speech + music
    engine = build_boosted_live_engine(profile='speech', enabled=True)
    def run(x):
        engine.reset_for_device_change()
        padded = np.pad(x, ((0,LATENCY_SAMPLES+480),(0,0)))
        return process(engine,padded)[LATENCY_SAMPLES:LATENCY_SAMPLES+len(x)]
    clean = run(speech)
    suppressed = run(music)
    enhanced = run(mix)
    assert attenuation_db(clean,speech) > -2
    assert si_sdr(clean,speech) > 20.3
    assert attenuation_db(suppressed[48000:],music[48000:]) < -44
    assert si_sdr(enhanced,speech) > si_sdr(mix,speech) + 5


def test_fast_profile_uses_real_model_and_suppresses_centered_music():
    x = instrumental(2)
    engine = build_boosted_live_engine(profile='speech-fast',enabled=True)
    y = process(engine,x)
    assert 'GTCRN' in engine.backend_name
    assert attenuation_db(y[48000:],x[48000:]) < -25


def test_vocal_conversion_preserves_consonant_band():
    from scipy.signal import freqz
    processor = SpeechSeparator()
    _, analysis = freqz(processor._fir, worN=[7000], fs=48000)
    _, synthesis = freqz(processor._synthesis_fir, worN=[7000], fs=48000)
    gain_db = 20 * np.log10(np.abs(analysis * synthesis))[0]
    assert abs(gain_db) < .5  # Previously this band lost almost 7 dB.


def test_detail_restoration_rejects_music_independently_per_channel():
    from silencio.speech import _VocalDetail
    stage = _VocalDetail(delay=480)
    source = instrumental(.01)
    stage.process(source, np.zeros_like(source))
    clean = source.copy()
    clean[:,0] *= .001  # Model rejects left Music.
    clean[:,1] *= .99  # Small right Vocal error can be restored.
    restored = stage.process(source,clean)
    np.testing.assert_array_equal(restored[:,0],clean[:,0])
    assert np.mean((source[:,1]-restored[:,1])**2) < np.mean((source[:,1]-clean[:,1])**2)
    stage.reset()
    assert not stage.process(source,np.zeros_like(source)).any()


@pytest.mark.parametrize('factory', [SpeechSeparator, FastSpeechSeparator])
def test_digital_silence_resumes_without_losing_vocal_or_changing_chunk_results(factory):
    voice = recorded('dialogue')[:24000]
    x = np.concatenate((voice,np.zeros((48000,2),np.float32),voice))
    processor = factory()
    a = process(processor,x,127)
    processor.reset()
    b = process(processor,x,2048)
    np.testing.assert_array_equal(a,b)
    assert not np.any(a[40000:70000])
    lag = processor.latency_samples
    assert attenuation_db(a[72000+lag:],voice[:-lag]) > -3
