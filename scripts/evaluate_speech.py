"""Reproducible paired-audio quality and processing-time check on this machine.

Run: python scripts/evaluate_speech.py --output .scratch/speech-report.json
Uses the attributed fixtures in tests/fixtures; never captures system audio.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from scipy.signal import correlate, correlation_lags
from silencio.boost import build_boosted_live_engine
from speech_material import recorded, instrumental, attenuation_db, si_sdr


def evaluate(profile):
    started = time.perf_counter()
    engine = build_boosted_live_engine(profile=profile, prefer='cpu', enabled=True)
    startup_ms = (time.perf_counter() - started) * 1000
    lag = engine.latency_samples
    timings = []
    speech = recorded('dialogue')
    music = recorded('music')
    music *= np.sqrt(np.mean(speech**2) / np.mean(music**2))

    def run(x):
        engine.reset_for_device_change()
        x = np.pad(x, ((0,lag+480),(0,0)))
        out = []
        for i in range(0,len(x),480):
            started = time.perf_counter()
            out.append(engine.process_block(x[i:i+480]))
            timings.append((time.perf_counter()-started)*1000)
        return np.concatenate(out)[lag:len(x)-480]

    clean = run(speech)
    music_out = run(music)
    mixture = speech + music
    enhanced = run(mixture)
    keys = instrumental()
    keys_out = run(keys)
    correlation = correlate(clean[:,0],speech[:,0],mode='full',method='fft')
    residual_lag = int(correlation_lags(len(clean),len(speech))[np.argmax(correlation)])
    return dict(profile=profile, backend=engine.backend_name, startup_ms=round(startup_ms,2),
        pipeline_delay_ms=lag/48, alignment_error_samples=residual_lag,
        instrumental_db=round(attenuation_db(keys_out[48000:],keys[48000:]),2),
        recorded_music_db=round(attenuation_db(music_out[48000:],music[48000:]),2),
        clean_vocal_level_db=round(attenuation_db(clean,speech),2),
        clean_vocal_si_sdr_db=round(si_sdr(clean,speech),2),
        mixture_input_si_sdr_db=round(si_sdr(mixture,speech),2),
        mixture_output_si_sdr_db=round(si_sdr(enhanced,speech),2),
        realtime_factor=round(float(np.mean(timings)/10),3),
        block_ms_p50_p95_p99_max=[round(float(x),3) for x in np.percentile(timings,[50,95,99,100])])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--profiles',nargs='+',default=['aggressive','speech-fast','speech','speech-quality'])
    args = parser.parse_args()
    reports = []
    for profile in args.profiles:
        report = evaluate(profile)
        reports.append(report)
        print(json.dumps(report,indent=2),flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(reports,indent=2)+'\n',encoding='utf-8')
    speech_reports = [r for r in reports if r['profile']=='speech']
    if speech_reports:
        r = speech_reports[0]
        assert r['instrumental_db'] < -25
        assert r['recorded_music_db'] < -44
        assert r['clean_vocal_si_sdr_db'] > 20.3
        assert r['clean_vocal_level_db'] > -2
        assert r['mixture_output_si_sdr_db'] > r['mixture_input_si_sdr_db']+5
        assert abs(r['alignment_error_samples']) <= 2
        assert r['realtime_factor'] < .85, 'Try speech-fast if this CPU cannot keep up'
