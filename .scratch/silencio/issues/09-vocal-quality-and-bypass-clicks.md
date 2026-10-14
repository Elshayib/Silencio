# 09: Preserve Vocal detail and fix clicks during OFF playback

Status: ready-for-human

Implementation and machine verification are complete. This records the
subjective listening limit; no implementation dependency remains.

## Request

The user confirmed Music filtering was satisfactory, requested better Vocal
quality, and identified the OFF noise as crackling/little clicks.

## Reproduction and causes

`python -m pytest tests/test_live_regressions.py -q -k 'off_never or gap_recovery'`
failed twice before the fixes. An OFF callback still invoked the model and
returned silence when it failed. Delaying capture callbacks caused a 0.2
single-sample amplitude jump into/out of an empty playback queue.

A 16-second live OFF baseline reported two underruns and approximately
3.7 ms processing per block. The old converter pair reduced 7 kHz by 6.97 dB.
Suspending OFF processing also exposed a legacy cold-start window bug:
`test_cold_start_mid_playback_has_no_amplified_window_edge` reproduced the
amplification near the first Hann-window edge. Complete overlap initialization
and a startup fade fix it without weakening toggle tests.

## Changes

- OFF skips the processor entirely after the existing crossfade. Resuming
  ON resets processor state on the audio thread.
- A bounded frame ring replaces the packet queue, retaining partial blocks,
  fading over discontinuities, and rebuffering after starvation.
- Live 44.1/48 kHz conversion uses a polyphase sinc filter rather than linear
  interpolation. Same-rate samples remain unchanged.
- The DPDFNet model and input filter are unchanged. A compensated output
  FIR preserves the 7 kHz band within 0.2 dB and adds only 1 ms.
- Conservative detail restoration operates only where aligned residual
  energy is below 2.5% of accepted Vocal energy, independently per channel.
  Rejected frames receive no restoration and there is no loudness gate.

## Evidence

`scripts/evaluate_speech.py --profiles speech`:

- Clean Vocal SI-SDR: 19.97 -> 20.53 dB; level -0.09 dB.
- Recorded Music attenuation: unchanged at 45.91 dB.
- Centered instrumental attenuation: unchanged at 68.52 dB.
- Equal-power mixture SI-SDR: unchanged at 5.84 dB (input -0.25 dB).
- Median processing: 4.62 ms per 10 ms block; p95 5.95 ms.
- Pipeline delay 63 ms, zero measured alignment error. The current device
  and buffer estimate is 147.7 ms ON / 84.7 ms OFF, not acoustic latency.

`scripts/check_live_playback.py --seconds 16` on the actual laptop route:
both OFF and ON had zero added underruns, overruns, processing deadline
misses or errors during the 32-second measurement. OFF processing peaked
at 0.105 ms (smoothed runtime statistic), ON at 5.06 ms. One startup overrun
and deadline miss occurred before the measurement; the test does not claim
the app can never drop audio under load.

121 tests passed; strict mypy passed for all 21 source files. Tests include
short/empty underrun tails, overflow discontinuities, stereo restoration,
converter fidelity/chunking, cold starts, OFF suspension, real Music and
Vocal, arbitrary driver block sizes, and reset/resume behavior.

Reports: `.scratch/vocal-quality-report.json` and
`.scratch/live-vocal-quality-report.json`. Debug experiments are contained
in the ignored `.scratch/speech-evaluation/` directory. No new model ships:
48 kHz DPDFNet2 required too much CPU headroom; phase restoration degraded
the known mixture. The app was restarted and left ON with `speech`.

## Limits

The measured Vocal improvement is modest; converter detail preservation
does not recover frequencies the speech model removed. The existing
speech-first model can still remove singing or other ambiguous human Vocal.
Neither the fixed corpus nor the live counters certify every recording or
prove the physical speakers never click. Buffer fades contain discontinuities
but cannot reconstruct audio Windows fails to deliver.
