# 02: Separator engine at buffer seam with clip harness

**What to build:** Streaming causal separation engine behind one buffer seam (mixed stereo PCM in, Vocal-plus-SFX stereo PCM out) with an offline harness that runs the three acceptance clips and demonstrates Vocal kept, Music suppressed including crowd and choir pads, SFX kept, and fail-open on ambiguous frames.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] Vocal song clip keeps lead singing intelligible with accompaniment strongly reduced
- [x] Movie dialogue over score keeps dialogue clear with score reduced
- [x] Game clip keeps dialogue plus effects with score reduced, stereo image preserved at 48kHz

## Comments

Implemented via `CausalSeparator` (causal STFT mask, numpy-only CPU) behind
the single engine buffer seam, plus deterministic acceptance clips and an
offline harness (`python -m silencio --clips`: 15/15 PASS).

- Song: Vocal band -1.7dB kept, Music bass -7.4dB, Music stem -8.7dB vs Vocal stem -0.5dB.
- Movie: dialogue band -0.1dB, Music stem -6.8dB vs Vocal -0.1dB, score-only gap -5.1dB.
- Game: dialogue band -0.2dB, Music stem -12.0dB vs Vocal -0.0dB, gap -7.0dB;
  gunshot peak +0.9dB, blip L/R -5.9dB vs stem -7.4dB with corr 0.83.
- Crowd/choir probe (glossary Music): -8.6dB. Ambiguous unison fails open:
  mix out vs Vocal +2.8dB (leaks Music, never clips Vocal).
- Seam properties preserved: toggle OFF bit-perfect, block-size
  deterministic (max diff 0.0), latency 1024 samples = 21.3ms (budget 150ms),
  CPU RTF ~0.11, no clicks. Full suite: 26 passed, mypy strict clean.
- Known residue (per spec "strong reduction, not silence"): narrow
  centered Music under active Vocal leaks (masked); hard-panned sustained
  content may thin (transients still pass); mono-narrow beds reduce less
  than wide ones.

## Review disposition (code-review skill, two axes)

- Glossary drift in scene prose kept deliberately: clip/scene labels
  (song, movie, game, dialogue bursts) quote the spec's own acceptance
  corpus ("vocal song", "movie dialogue over score", "game capture");
  domain-concept prose uses Vocal / Music / SFX throughout.
- Deferred to owner tickets, not this one: 44.1kHz resampling (03 live
  wiring owns the input path; the seam contract stays 48kHz-only),
  ON/OFF loudness parity (06 acceptance-hardening checklist), end-to-end
  capture-to-render latency proof (04 soak; here only the 21.3ms
  separator share is asserted).
- Engine realization note: v1 ships causal heuristic DSP (numpy-only,
  CPU, no weights, no network) instead of an ONNX TasNet/X-UMX, because
  the repo has no weights, no network access, and a CPU-only floor; it
  meets the same contract both ADRs require (streaming-causal,
  fail-open, local-only, strong-not-silent reduction). Mitigations
  against tuning-to-own-clips: relative stem margins (Music hurt 2dB+
  more than Vocal), convention-breaking probes (centered unison kept,
  diffuse crowd cut), OFF bit-perfect and block-size determinism.
- Footstep thump peak coverage added (bass-transient path); gunshot,
  blip L/R and blip correlation already covered.
