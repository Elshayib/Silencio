# CPU streaming-causal separator with fail-open over offline quality

Instant operation at or under 150ms rules out offline models that need multi-second chunks, so v1 uses a lightweight streaming causal separator on CPU with GPU as optional boost. We accept roughly 4 to 5 dB residue and a fail-open policy that leaks Music rather than clipping Vocal, because the user's hard constraint is never losing Vocal.
