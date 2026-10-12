# 02: Separator engine at buffer seam with clip harness

**What to build:** Streaming causal separation engine behind one buffer seam (mixed stereo PCM in, Vocal-plus-SFX stereo PCM out) with an offline harness that runs the three acceptance clips and demonstrates Vocal kept, Music suppressed including crowd and choir pads, SFX kept, and fail-open on ambiguous frames.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Vocal song clip keeps lead singing intelligible with accompaniment strongly reduced
- [ ] Movie dialogue over score keeps dialogue clear with score reduced
- [ ] Game clip keeps dialogue plus effects with score reduced, stereo image preserved at 48kHz
