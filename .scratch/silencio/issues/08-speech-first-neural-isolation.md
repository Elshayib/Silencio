# 08: Replace spectral guessing with local neural spoken-Vocal extraction

Status: ready-for-human

Implementation is complete; this ticket records the remaining subjective
listening limitations rather than an outstanding implementation dependency.

## Request

Music still remained audible after ticket 07. The user explicitly selected
spoken dialogue over singing and asked for the strongest practical suppression
with responsive playback on this Ryzen 5 7520U / 8 GB laptop.

## Reproduction

The previous aggressive profile attenuated a centered changing instrumental
probe by only 0.34 dB, despite the existing 90-test suite passing. The new
test drives the actual streaming engine and requires at least 25 dB.

## Implemented

- Bundled, checksum-verified DPDFNet baseline model for the default `speech`
  profile; optional DPDFNet2 `speech-quality` and GTCRN `speech-fast` profiles.
- Independent stereo recurrent states, band-limited 48/16 kHz conversion,
  fixed-size streaming buffers, warmup before opening devices, and no dry
  Music burst when starting ON. No runtime downloads or audio uploads.
- Digital-silence idle mode that drains the model tail and resumes with clean
  state; quiet nonzero Vocal is never volume-gated.
- Correct 62 ms DPDFNet / 34 ms GTCRN pipeline-delay accounting, including
  the otherwise hidden four-hop DPDFNet delay. The live driver/buffer
  estimate for this cable/speaker pair is 146 ms with the default model.
- Actual backend, processing-time, missed-deadline and dropout diagnostics.
- Windows file-sharing retries and best-effort heartbeat writes: a diagnostic
  reader reproduced a PermissionError that previously terminated live audio.
- Launcher readiness verification, stale-process detection, and a default
  that starts the new speech model ON.

## Quality evidence

The attributed eight-second recordings and their equal-power mixture are in
`tests/fixtures`. `scripts/evaluate_speech.py` compares the actual streaming
engines, compensates their measured delays, and exports repeatable results.

On the fixed corpus, the old aggressive profile attenuated recorded Music
by 6.58 dB; the new default attenuated it by 45.91 dB. Clean Vocal level
changed by -0.11 dB. Mixture SI-SDR improved from -0.25 dB input to 5.84 dB
output. Isolated-stem suppression is not a claim of equivalent removal
when Music overlaps Vocal.

DPDFNet2 achieved 6.37 dB mixture SI-SDR but produced substantially more
live underruns. The baseline model is the default for CPU headroom; the
heavier model remains explicit. A trial one-block worker bridge worsened
WASAPI burst handling and was removed, rather than shipping unstable code.

## Verification and limits

Regression coverage includes centered changing Music, recorded mixtures,
opposite-phase Vocal, block chunking, reset, digital-silence resume, OFF
passthrough, startup Music leakage, damaged models, and Windows heartbeat
locks. Licenses and models are included in the built wheel.

Real cable playback reached the default speech engine and speakers without
processing errors. The initial 15-second baseline check reported two
underruns, zero overruns, and approximately 4.5 ms processing per 10 ms
block. This is a driver check, not a claim of perfect acoustic lip-sync or
zero dropouts under all system loads. Final results are retained in
`.scratch/speech-report.json` and `.scratch/live-speech-report.json`.

Arbitrary recordings, languages, whispered/distant Vocal, and loud Music
can behave differently. Perfect Music removal with zero delay and no Vocal
damage is not established by these tests. Singing and SFX may be removed,
as authorized by the user's speech-first preference.

## Final verification (2026-10-14)

- Full suite: 106 passed; strict mypy: 20 source files clean.
- Built wheel verified against all three model SHA-256 values and notices.
- Final cable playback: no processing errors or processing deadline misses;
  one underrun and one overrun counter increment during the test. These
  counters are retained instead of claiming flawless hardware playback.
- Digital-silence processing measured approximately 0.012 ms per 10 ms block.
- Live process left ON with the laptop `speech` profile and tray/hotkey controls.
