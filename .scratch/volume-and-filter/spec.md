# Windows volume/mute repair and instruments-only investigation

Requested 2026-10-16: changing volume has little effect and zero remains
audible. Audit related mute/volume behavior. Investigate preserving clapping,
audience sounds, and other non-instrumental content while removing instruments.
Clarification: prioritize strong Music removal, accepting some audience loss.

Acceptance: Windows master and media-key controls reach the chosen render
endpoint with suppression ON and OFF; zero/mute silences buffered output;
unmute recovers; restarting/changing output/profile preserves listening state;
shutdown preserves the final volume/mute. No COM or disk work in callbacks.

For filter work, retain the current suppression default unless a candidate
passes separate Music-rejection, audience-retention, overlap, and live latency
checks. Research is in [filter-research.md](filter-research.md).
