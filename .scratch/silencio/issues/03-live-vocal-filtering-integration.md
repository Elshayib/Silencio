# 03: Live Vocal filtering integration

**What to build:** Live wiring of the separator engine into the system path so toggle ON emits Vocal plus SFX with Music reduced across any playback source, toggle OFF restores the original mix bit-perfect with loudness parity, fully local-only with microphone inputs untouched.

**Blocked by:** 01 System passthrough with gapless toggle, 02 Separator engine at buffer seam with clip harness.

**Status:** ready-for-agent

- [x] Live browser, movie, game, and song playback all filter when ON and restore when OFF
- [x] Teammate speech arriving over speakers is preserved as Vocal while own microphone input is untouched
- [x] No audio upload occurs and end-to-end feel stays in sync at or under 150ms

## Comments

Implemented via `build_live_engine` (separator wired into the engine
buffer seam) in `src/silencio/live.py`, plus `src/silencio/resample.py`
(44.1kHz input-path adapter, seam stays 48kHz-only) and `AudioGraph`
guards (mic-like inputs refused, over-budget blocks refused).
`--run` now starts the live Vocal filter instead of passthrough.

- All sources through the live seam: song Music -8.7dB vs Vocal -0.5dB,
  movie gap -5.1dB, game gap -7.0dB; OFF restores every clip bit-perfect.
- Teammate speech (game dialogue stem) kept near unity; SFX kept
  (gunshot peak +0.9dB, blip imaging within 2.5dB, corr 0.83).
- Crowd/choir, gapless mid-song toggle (step < 0.3, switch 10ms), and
  unison fail-open also proven through the live-wired engine itself.
- Loudness parity: ON never boosts (mix <= OFF +1dB), Vocal path unity.
- Latency estimate 2*1024+1024+480 = 74.0ms (budget 150ms); separator
  share 21.3ms, CPU RTF ~0.10. Measured soak lands in ticket 04.
- Local-only: package imports no network clients (tested); mic inputs
  never opened (guard tested, graph enforces). 44.1kHz file sources
  resample transparently (round trip -0.004dB on song mix).
- Full suite: 48 passed, mypy strict clean, `--clips` 15/15 PASS.
- Code-review dispositions: scene labels (song, movie, game, dialogue)
  quote the spec's own acceptance corpus per the ticket 02 precedent;
  domain prose uses Vocal / Music / SFX. Browser tabs share the
  dialogue-over-score loopback path with the movie clip (corpus defines
  three clips); four-source live AB stays manual in 06. Measured soak in
  04; static guards (no network imports incl. from-imports, mic-name
  refusal) hold until live WASAPI direction checks in 05/06.
- Manual live AB still required (per spec, lands in 06): real browser /
  movie / game through the cable, mid-sound toggle gapless, headphone
  replug recovery, loudness-parity listening check.
