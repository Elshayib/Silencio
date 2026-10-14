# Speech-first neural filtering for stronger Music suppression

The user explicitly prioritized spoken Vocal and stronger Music removal on
2026-10-13, accepting loss of singing and SFX. This supersedes ADR-0002's
fail-open ambiguity policy for the default `speech` profile: use bundled
DPDFNet with separate stereo states, keep ON audio fully processed, and
mute on processing failure rather than pass the original Music through.
Retain DPDFNet2 as `speech-quality`, GTCRN as `speech-fast`, and the earlier spectral
profiles as explicit alternatives; processing remains local and output-only.

DPDFNet baseline improved paired-mixture SI-SDR by about 6 dB over input.
DPDFNet2 scored about 0.5 dB better but caused more live dropouts on this
Ryzen 5 7520U laptop, so the lighter variant is the default. Both add 62 ms
pipeline delay. Include the model's internal four-hop delay in
latency reporting; keep the hardware bridge bounded and report overruns,
underruns and processing deadline misses. Neither low latency nor these
fixture results imply perfect separation of arbitrary recordings.
