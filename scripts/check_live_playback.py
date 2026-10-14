"""Exercise the running cable route ON/OFF with known local fixtures.

Plays low-level test material into CABLE Input; never opens a capture device
or microphone. Restores the original toggle even when a check fails.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

from silencio.graph import default_state_path
from silencio.runtime import read_runtime
from silencio.state import ToggleStateStore
from speech_material import recorded


def check(seconds: float) -> list[dict]:
    state = default_state_path()
    store = ToggleStateStore(state)
    original = store.load()
    initial = read_runtime(state)
    assert initial and initial['running'], 'Start Silencio first'
    devices = sd.query_devices()
    host = devices[initial['input_device']]['hostapi']
    cable = next(i for i,d in enumerate(devices)
                 if d['hostapi'] == host and 'cable input' in d['name'].lower()
                 and d['max_output_channels'] >= 2)
    rate = int(devices[cable]['default_samplerate'])
    voice, music = recorded('dialogue'), recorded('music')
    music *= np.sqrt(np.mean(voice**2) / np.mean(music**2))
    material = np.tile(voice + music, (int(np.ceil(seconds/8)),1))[:round(seconds*48000)]
    material *= .12 / np.max(np.abs(material))
    material = resample_poly(material,rate,48000).astype(np.float32)
    reports = []
    try:
        for enabled in (False, True):
            store.save(enabled)
            deadline = time.monotonic() + 3
            while True:
                before = read_runtime(state)
                if before and before['enabled'] == enabled:
                    break
                assert time.monotonic() < deadline, 'Live toggle did not update'
                time.sleep(.1)
            # Let the fade settle before starting this measurement.
            time.sleep(.2)
            before = read_runtime(state)
            observations = []
            sd.play(material,samplerate=rate,device=cable)
            while sd.get_stream().active:
                time.sleep(.5)
                current = read_runtime(state)
                assert current and current['running'] and current['pid'] == initial['pid']
                assert current['enabled'] == enabled and current['error'] is None
                observations.append(current)
            sd.stop()
            after = observations[-1]
            report = dict(enabled=enabled, seconds=seconds, latency_ms=after['latency_ms'],
                          peak_processing_ms=max(o['processing_ms'] for o in observations),
                          peak_input_rms=max(o['input_rms'] for o in observations),
                          peak_output_rms=max(o['output_rms'] for o in observations),
                          error=after['error'])
            report.update({k+'_added':after[k]-before[k]
                           for k in ('underruns','overruns','deadline_misses','captured_frames')})
            assert report['peak_input_rms'] > .001 and report['peak_output_rms'] > .001
            assert report['captured_frames_added'] > seconds * 40000
            reports.append(report)
            print(json.dumps(report,indent=2),flush=True)
    finally:
        sd.stop()
        store.save(original)
    return reports


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=float,default=16)
    parser.add_argument('--output',type=Path,default=ROOT/'.scratch/live-vocal-quality-report.json')
    args = parser.parse_args()
    assert 4 <= args.seconds <= 60
    result = check(args.seconds)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
