"""Deterministic instrumental probes; these are not perceptual quality scores."""
import numpy as np
from pathlib import Path


def instrumental(seconds=4.0, sample_rate=48000):
    t = np.arange(round(seconds * sample_rate)) / sample_rate
    beat = np.floor(t * 4).astype(int)
    notes = np.array([220, 277.18, 329.63, 440, 392, 329.63, 277.18, 246.94])
    freq = notes[beat % len(notes)]
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate
    envelope = np.exp(-8 * np.mod(t, .25)) * np.minimum(np.mod(t, .25) / .004, 1)
    keys = sum(np.sin(phase * k) / k**1.4 for k in range(1, 9)) * envelope
    # Centered changing notes defeat stereo-width and sustained-tone heuristics.
    return np.repeat((keys * .18).astype(np.float32)[:, None], 2, axis=1)


def attenuation_db(output, source):
    return float(10 * np.log10((np.mean(output.astype(float)**2) + 1e-20) /
                             (np.mean(source.astype(float)**2) + 1e-20)))


def recorded(name):
    from scipy.io import wavfile
    from scipy.signal import resample_poly
    rate, audio = wavfile.read(Path(__file__).parent / 'fixtures' / (name + '.wav'))
    mono = resample_poly(audio.astype(np.float32) / 32768, 48000, rate)
    return np.repeat(mono[:, None], 2, axis=1)


def si_sdr(output, reference):
    y = output.astype(np.float64).ravel()
    x = reference.astype(np.float64).ravel()
    wanted = x * (np.dot(x,y) / (np.dot(x,x) + 1e-20))
    return attenuation_db(wanted, y - wanted)
