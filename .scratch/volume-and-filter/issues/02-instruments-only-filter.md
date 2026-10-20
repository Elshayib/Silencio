# 02: Investigate preserving audience sounds during strong Music suppression

Status: ready-for-human

Research is complete; a model replacement has not been validated or shipped.

## Finding

DPDFNet is trained for speech enhancement and cannot label arbitrary rejected
audio as either an instrument or applause. The user explicitly chose strong
Music removal over broad restoration of audience sounds. The default model
and suppression strength therefore remain unchanged.

[Research and sources](../filter-research.md) identify Bandit v2 as an offline
quality reference whose effects training includes applause/clapping, and
Waveformer as a causal applause-extraction experiment. Neither is established
as a strong, instruments-only, stereo replacement within this laptop's live
latency and CPU budget. The note records licenses, source/config constraints,
and the benchmark gates required before adoption.

The glossary and ADR-0006 now distinguish the desired instruments-only target
from the current model's known audience-loss limitation.
