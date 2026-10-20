# Instrument removal while preserving applause and audience sounds

Researched: 2026-10-16. Scope: local Windows playback, Ryzen 5 7520U CPU,
stereo, approximately 150 ms total latency. The user explicitly prioritizes
strong Music removal when that conflicts with preserving audience sounds.

## Recommendation

Keep the present strong default until a candidate passes a paired listening
and leakage benchmark. Do not increase the dry mix, lower the speech gate,
or treat all transients as safe: those changes also admit percussion and
other instruments. Investigate a **cinematic dialogue/music/effects
separator** as the replacement target, with Bandit v2 as the first offline
quality reference. For the live CPU implementation, evaluate a causal
target-sound model such as Waveformer as an experimental applause extractor
or architecture reference, not as a proven replacement.

None of the reviewed releases establishes the combination of this laptop's
CPU budget, strong instrument suppression, preserved audience sounds, and
stereo coherence. This is a limitation of the evidence, not a claim that
such a model cannot be built. No candidate model was installed or benchmarked
in this investigation.

## Why the current filter removes these sounds

The bundled default is DPDFNet **speech enhancement**, not instrument-stem
separation. Its intended target is speech; applause and most effects are
therefore eligible for suppression. The local model README already records
that singing, distant/quiet Vocal, and SFX can be lost. Changing a threshold
cannot give the network a new semantic target. [Bundled model notes](../../src/silencio/models/README.md),
[speech-first decision](../../docs/adr/0004-speech-first-neural-filter.md).

The old `GLOSSARY.md` included human crowd in Music and excluded crowd from
Vocal. Today's request wants non-instrumental sound preserved where compatible
with strong instrument removal. The glossary and
[ADR-0006](../../docs/adr/0006-instruments-only-target-with-strong-suppression.md)
now record that target. Musical backing vocals and natural cheering should
also be evaluated separately; model stem labels need not match the product's
desired boundary. [Current terminology](../../GLOSSARY.md).

## Candidates and constraints

### Bandit v2 / DnR v3: best task match, offline reference first

The DnR v3 training definition explicitly retains **Clapping** and
**Applause** in the effects material. It excludes other human-group-action
classes and removes detected speech/music from effects. This makes applause
a meaningful supported test target, but does not prove preservation of
cheers, chants, crowd speech, or singing. DnR v3 is mono; the authors warn
that processing channels independently can affect phase coherence.
[Authors' paper, sections II-A and II-D](https://arxiv.org/html/2407.07275v1).

The released model configuration uses bidirectional GRUs and centered STFT.
The official inference configuration uses **8-second chunks, 1-second hops**
at **48 kHz**; the entry point sends both model and audio to CUDA. These are
noncausal/offline defaults, not Silencio's frame-state contract. Shortening
the chunks is an experiment with quality and CPU consequences, not a
guarantee of 150 ms operation. [Model configuration](https://github.com/kwatcharasupat/bandit-v2/blob/d5563d9031e95fdaa3e5a73d5020b9a0df61adb6/configs/models/bandit-mus64.yaml),
[chunk configuration](https://github.com/kwatcharasupat/bandit-v2/blob/d5563d9031e95fdaa3e5a73d5020b9a0df61adb6/configs/inference/chunked-tensor-a100.yaml),
[inference settings](https://github.com/kwatcharasupat/bandit-v2/blob/d5563d9031e95fdaa3e5a73d5020b9a0df61adb6/expt/inference.yaml),
[entry point](https://github.com/kwatcharasupat/bandit-v2/blob/d5563d9031e95fdaa3e5a73d5020b9a0df61adb6/inference.py).

Code is Apache-2.0; **weights are CC BY-SA 4.0**, separately. The official
README links Zenodo record 12701995. Both the Zenodo API and its deposited
DOI metadata identify these model weights as CC BY-SA 4.0; each released
checkpoint is approximately 447 MB. Preserve both licenses and attribution if evaluating
or distributing a conversion. [Code license](https://github.com/kwatcharasupat/bandit-v2/blob/d5563d9031e95fdaa3e5a73d5020b9a0df61adb6/LICENSE),
[official weights record](https://zenodo.org/records/12701995),
[record metadata](https://zenodo.org/api/records/12701995),
[DOI metadata](https://api.datacite.org/dois/10.5281/zenodo.12701995).

### MVSEP CDX23: useful comparison, not a streaming upgrade

This Demucs-based release separates dialog/effect/music. Its authors warn
that its DnR music stem can include vocals, so it does not exactly implement
instruments-only removal. Inference accepts CPU but uses whole-file model
application with 80% overlap; the high-quality option ensembles three
checkpoints. CPU support is not evidence of CPU real-time performance.
[Official README](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing),
[inference implementation](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing/blob/aaa75640d8fd68418948fe4cd2c2d263d042cbb9/inference.py).

The bundled HTDemucs class defaults to a 10-second segment and can use its
training segment during inference. The exact released checkpoint's segment
must be inspected before reporting its latency; this investigation did not
load the weights. Code is MIT. The official weight release has three
approximately 54 MB checkpoints and no separate explicit weight-license
statement; do not infer one solely from the code license.
[Model source](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing/blob/aaa75640d8fd68418948fe4cd2c2d263d042cbb9/demucs4/htdemucs.py),
[code license](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing/blob/aaa75640d8fd68418948fe4cd2c2d263d042cbb9/LICENSE),
[weight release](https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing/releases/tag/v.1.0.0).

### AudioSep: flexible semantic benchmark, substantial integration mismatch

AudioSep extracts a sound described by text, including instruments and
environmental events. The provided pipeline downmixes to mono at 32 kHz.
Its chunked path uses 1 second of left context, a 3-second central region,
and 1 second of right context; convolution padding and STFT are noncausal.
It is not a low-latency stereo streaming implementation. A prompt for
"music" also needs careful testing because it can include singing.
[Official project](https://github.com/Audio-AGI/AudioSep),
[pipeline](https://github.com/Audio-AGI/AudioSep/blob/944583f18b84589dc965de3ad77525c945334252/pipeline.py),
[model and chunking](https://github.com/Audio-AGI/AudioSep/blob/944583f18b84589dc965de3ad77525c945334252/models/resunet.py).

Code is MIT; the authors' official Hugging Face Space hosting the separation
and CLAP checkpoints is also marked MIT. There is no detailed per-checkpoint
model card there, so preserve the exact source and investigate bundled
dependencies separately before redistribution. Local CPU throughput is
unmeasured. [Code license](https://github.com/Audio-AGI/AudioSep/blob/944583f18b84589dc965de3ad77525c945334252/LICENSE),
[official checkpoint-host license metadata](https://huggingface.co/spaces/Audio-AGI/AudioSep/blob/0807a713283035d8b0d0628f1b8e3d6580459f7b/README.md).

### Waveformer: directly relevant causal research lead

The authors provide streaming inference and report approximately 10 ms input
chunks, less than 20 ms end-to-end latency, and single-thread Core i5
real-time factors of 0.66–0.94. Its fixed target list includes **Applause**,
laughter and several instruments, but no generic speech, crowd, or all-music
class. It therefore cannot replace the complete filter as shipped.
[Official implementation and measurements](https://github.com/vb000/Waveformer),
[exact target list](https://github.com/vb000/Waveformer/blob/db51a4916e8001db1d6fde8cc9c19a3bed82a1b5/Waveformer.py).

An applause-only branch is worth testing against drums, percussion and
applause-plus-score mixtures. Do not add that output to the live path until
leakage, alignment, duplicate content, and combined stereo CPU cost pass.
The reported i5 results do not benchmark this Ryzen, and adding another
network consumes headroom already needed by DPDFNet. Code is MIT; the linked
external checkpoint downloads have no separate weight license established
by this review. [License](https://github.com/vb000/Waveformer/blob/db51a4916e8001db1d6fde8cc9c19a3bed82a1b5/LICENSE),
[checkpoint distribution reference](https://github.com/vb000/Waveformer#training-and-evaluation).

### Newer streaming music models: promising architecture, wrong proven labels

Band-SCNet reports 92 ms model latency and 2.59 M parameters on MUSDB18-HQ.
RT-STT studies a causal lightweight music separator. Both concern the
vocals/drums/bass/other task; those results do not establish that applause
survives in the retained output. No deployable official code-and-weights
package with verified licensing was established for either here.
[Band-SCNet paper](https://www.isca-archive.org/interspeech_2025/yang25d_interspeech.pdf),
[RT-STT paper](https://arxiv.org/html/2511.13146v1).

A September 2026 DSP paper reports a measured 10.43 ms frame runtime, but
also evaluates music's four-stem task, explicitly leaves domain robustness
untested, and says runtime/profiling resources will be released. Its custom
DSP figures are not a Windows CPU benchmark. Another September 2026 paper
shows low-latency adaptation of offline separators, but reports that only
HT-Demucs runs faster than real time on a GPU in its streaming experiments.
These motivate future engineering, not a shipped replacement claim.
[DSP study](https://arxiv.org/html/2609.12201v1),
[offline-to-streaming study](https://arxiv.org/abs/2609.35397).

## Concrete evaluation gate

1. Build a small fixture set with isolated stems and provenance: spoken Vocal,
   isolated instruments, clapping/applause, crowd speech/cheering, laughter,
   impacts, footsteps, and singing. Include instrument-free examples and
   mixtures of speech + effects + instruments at several level ratios.
   Distinguish natural applause from rhythmic claps used as percussion.
   Use the existing licensed speech/music fixtures; add self-recorded or
   individually licensed effects with attribution and hashes.
2. Record baseline DPDFNet results before changing it. Measure target
   distortion on speech + desired effects, retained applause energy on
   isolated effects, and instrument attenuation on isolated music. For
   mixtures, use the known target and interference stems, not just output
   RMS: silence scores well on suppression but fails preservation.
3. Run Bandit v2 offline and keep only estimated dialogue + effects. Compare
   directly with the default and inspect crowd/cheer failures. This establishes
   whether a better target yields useful improvement before attempting a
   streaming conversion or training a smaller causal model.
4. Separately test Waveformer Applause against isolated drums, mixed percussion,
   applause + music, and speech + applause + music. Only explore a combined
   output after it demonstrates no material regression in instrument removal.
5. Require meaningful preservation improvement without worse Music leakage
   than the accepted default. Review the worst cases by listening, including
   speech, singing, stereo motion, and silence. Do not equate an average SDR
   improvement with meeting this user's preference.
6. On this exact laptop, measure sustained stereo processing, worst/p95/p99
   block time, underruns, working memory, and full capture-to-render latency,
   with browser playback and ordinary load. Include resampling, model context,
   and bridge queues in the approximately 150 ms budget. A candidate stays
   experimental unless those checks pass.

The actionable product change now is honest filter labeling plus this
evaluation gate. A production model swap requires evidence that was not
available from these papers or release configurations alone.
