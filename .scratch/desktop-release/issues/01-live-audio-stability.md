# Eliminate intermittent live audio underruns

Status: ready-for-agent
Type: task

## Problem

The packaged Everyday filter occasionally misses audio deadlines on the
development PC. In the final 30-second ON fixture run it added one underrun
and three processing deadline misses; OFF was clean. A preceding 16-second
installed run added three underruns. Short source and packaged comparisons
can both pass, so a single clean run is insufficient evidence.

## Reproduction

Start the installed app with Everyday selected, then run without simultaneous
builds or tests:

```powershell
python scripts/check_live_playback.py --seconds 30 --max-underruns 0 --output .scratch/release-validation/audio-stability.json
```

The final observed command exited with `Audio underrun limit exceeded`.
Raw reports: `.scratch/release-validation/final-unlocked-playback.json` and
`final-installed-playback.json`.

## Findings

- Source and frozen copies both averaged about 4.6 ms in matched short runs;
  a consistent packaging slowdown was not demonstrated.
- Avoiding redundant desktop redraws improved one run but did not eliminate
  the intermittent failures.
- Failures also occurred after Windows was unlocked.
- The combined underrun counter includes driver and bridge shortages. Capture
  timing of those two causes separately before changing buffering or scheduling.
- Preserve the approved default model, suppression quality, bounded buffers,
  and latency requirements. Do not hide failures by relaxing the diagnostic.

## Acceptance

Identify the cause with measured evidence, verify against the existing live
fixture on repeated playback/resume runs, and cover any deterministic software
cause at its actual seam. Broader hardware testing remains necessary.

## Comments

2026-10-15: Retained as an explicit blocker for the final public release.
The unsigned RC is available for testing; no zero-dropout guarantee is made.
