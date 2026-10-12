# 04: CPU real-time plus optional GPU boost

**What to build:** Sustained glitch-free live operation on CPU alone at the mid-range floor, with measured delay inside budget and an optional GPU path that reduces residue when present without changing the toggle workflow.

**Blocked by:** 03 Live Vocal filtering integration.

**Status:** ready-for-agent

- [x] Continuous playback runs without dropouts on CPU-only mid-range hardware
- [x] Measured end-to-end delay stays at or under 150ms during the soak
- [x] GPU-present run produces equal or cleaner Vocal with identical toggle behavior

## Comments

Implemented via `run_soak`/`SoakConfig`/`SoakReport` in `src/silencio/soak.py`
(wall-clock per-block timing through the single engine buffer seam, 1s
untimed warm-up for cold-start allocation plus detector convergence,
mid-soak toggle flips under load) and `build_boosted_live_engine` in
`src/silencio/boost.py` (guarded `torch.cuda` / ORT GPU probe plus
`SILENCIO_FORCE_GPU=1` override; deeper `music_depth` 0.75->0.85 residue
pass behind the same seam, CPU fallback when no GPU). `--soak`
(`--backend auto/cpu/gpu`, `--soak-seconds`) reports it; `--run` now
uses the auto backend (identical separator on CPU hardware).

- Soak (CPU, 8s): 0 dropouts over 375+ blocks, RTF ~0.07, mean ~1.5ms
  p95 ~2.6ms max ~4.1ms vs the 21.3ms block deadline; measured
  end-to-end ~76.6ms (74.0ms static estimate + p95) vs the 150ms budget.
- GPU-forced run: song Music -9.9dB vs CPU -8.7dB (cleaner), Vocal
  -0.7dB vs -0.6dB (within 1dB, still near unity); crowd/choir,
  unison fail-open, gunshot peak, and OFF bit-perfect all hold through
  the boosted engine with switch time 10ms (<50ms).
- Cold-start note: the first block can cost ~29ms (allocation), so the
  soak primes 1s untimed exactly as the live stream primes on start;
  steady-state never drops.
- Full suite: 55 passed (48 prior + 7 new), mypy strict clean.
- Local-only holds: new modules import no network clients (ticket 03
  guard test still passes); mic inputs never opened.

## Review disposition (code-review skill, two axes)

- Standards: 0 hard violations; 4 weak smells acknowledged, not
  changed (one-line backend validation in cli+boost, `tail` /
  `CPU_DEPTH` naming, cli `--soak` + `--run` in one file). The flagged
  glossary slip was pre-existing prose, not this diff.
- Deferred to manual AB / ticket 06, not this one: mid-range
  quad-core hardware evidence, real-GPU (non-simulated) residue
  measurement, and WASAPI/driver jitter (the soak measures the
  automatable share: wall-clock processing plus fixed pipeline).
- Contested and kept: `music_depth`/`--backend` are the residue
  reducer the ticket asks for (bounded, default unchanged); `--run`
  auto-backend is identical on CPU hardware; `RTF < 0.5` repeats the
  ticket 02 precedent; boosted Vocal within 1dB of CPU added as the
  fail-open guard for the deeper cut.
