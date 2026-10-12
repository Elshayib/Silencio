Status: ready-for-agent

# Silencio — live system-wide Vocal isolation

## Problem Statement

I play audio from anywhere on my PC — browser tabs, movies, games, songs — and I want to hear people, not background sound. Today there is no single switch that removes Music across the whole system while keeping Vocal and SFX intelligible and in sync. Per-app removers and offline file tools do not help when I just press play.

## Solution

A live Windows filter that sits on all speaker output with a single global toggle. When ON, the listener hears Vocal plus SFX with Music strongly reduced; when OFF, the listener hears the original mix bit-perfect. Switching is instant and gapless, processing stays fully on-machine, and the worst case on ambiguous sound favors keeping Vocal over removing more Music.

## User Stories

1. As a listener, I want a single global toggle for the whole system, so that any playback source is filtered without per-app setup.
2. As a listener, I want toggle ON to preserve Vocal, so that speech, dialogue, and lead singing stay intelligible.
3. As a listener, I want toggle ON to preserve SFX, so that gunshots, footsteps, UI cues, and film effects stay audible alongside Vocal.
4. As a listener, I want toggle ON to suppress Music, so that instruments and background score drop far into the background.
5. As a listener, I want crowd and choir pads treated as Music, so that stadium noise and backing oohs do not leak through as if they were Vocal.
6. As a listener, I want toggle OFF to restore the original mix bit-perfect, so that I can compare or enjoy full songs without reinstalling anything.
7. As a listener, I want the toggle switch to be gapless with no pop or click, so that I can flip it mid-song or mid-dialogue.
8. As a listener, I want a global hotkey plus tray control for the toggle, so that I can switch while a game or fullscreen movie has focus.
9. As a browser watcher, I want YouTube and streaming tabs filtered live, so that dialogue over score stays clear.
10. As a movie watcher, I want film dialogue kept with score suppressed, so that quiet speech is understandable without raising volume.
11. As a gamer, I want teammate speech arriving over speakers kept, so that callouts survive while game Music is reduced.
12. As a gamer, I want positional SFX imaging preserved in stereo, so that direction cues still work when the filter is ON.
13. As a song listener, I want lead singing kept with accompaniment reduced, so that I can follow lyrics over a full band mix.
14. As a latency-sensitive user, I want end-to-end delay at or under 150ms, so that lip-sync and game reactions stay usable.
15. As a laptop user without a discrete GPU, I want the filter to run on CPU alone, so that I am not forced to buy hardware.
16. As a GPU owner, I want optional GPU acceleration to reduce residue, so that better hardware gives cleaner Vocal without changing workflow.
17. As a privacy-conscious user, I want all processing fully offline on my machine, so that no system audio is ever uploaded.
18. As a headset user, I want the filter to survive headphone unplug and replug plus default-device changes, so that I do not have to restart the tool.
19. As a new user, I want guided setup that installs the virtual output, sets it as Default Playback, and disables exclusive-mode, so that system-wide capture actually works.
20. As a listener on ambiguous mixes, I want the filter to fail open toward Vocal, so that an unsure moment leaks a little Music instead of clipping speech.
21. As a listener, I want consistent loudness between ON and OFF states, so that toggling does not blast or mute me.
22. As a streamer, I want my own microphone input left untouched, so that only what I hear is filtered and what others hear from me is unchanged.

## Implementation Decisions

- Target Windows 10/11 64-bit only for v1; no cross-platform support.
- Audio graph is a virtual-cable loopback chain: a virtual output becomes Default Playback, the tool captures its loopback, processes, and renders to the real speakers. No custom driver or APO for v1.
- Separation engine is a lightweight streaming causal model (causal TasNet / X-UMX-causal class, ONNX, stereo), chosen for instant operation over offline-quality models.
- Pipeline runs stereo at 48kHz with resampling of 44.1kHz sources, preserving the stereo image of Vocal and SFX; no mono downmix.
- Latency budget is at most 150ms end-to-end (capture plus hop plus overlap plus render); v1 accepts audible residue and thinner Vocal compared with offline separation as the price of instant operation.
- Compute floor is CPU-only operation on a mid-range quad-core (i7 / Ryzen 5 class); GPU, when present, is an optional residue reducer, never a requirement.
- Toggle semantics are gapless bypass: ON emits Vocal plus SFX, OFF passes the original mix through untouched, with switch time under 50ms and persisted state across restarts.
- Scope is speaker-output render path only; microphone capture devices are never processed. Teammate speech is in scope only as it arrives over speakers as Vocal.
- Privacy architecture is local-only; no audio leaves the machine and no network is required at runtime.
- Ambiguity policy is fail-open: on unison pitch, bass bleed, or low-confidence frames, preserve Vocal at the cost of leaking Music.
- Setup requires admin rights, virtual-output install, reboot, manual Default Playback selection, exclusive-mode off, and app restart; this friction is accepted for v1.
- Expected separation quality is strong reduction, not silence: roughly 4 to 5 dB signal-to-distortion on streaming models, meaning faint residue and slight phasiness on hard mixes.

## Testing Decisions

- A good test asserts externally audible behavior (Vocal intelligible, Music reduced, SFX kept, no pops, delay bounded), never model weights or internal layer shapes.
- Greenfield repo: there are no existing seams or prior test suites to reuse.
- Proposed seam (single, highest stable point): one engine buffer seam — mixed stereo PCM block in, Vocal-plus-SFX stereo PCM block out. All acceptance clips run through this seam deterministically without needing a virtual cable or live driver. This matches your expectation of one seam unless you object.
- System graph behavior (loopback capture to speaker render, hotkey toggle, device-change survival) is verified manually via live AB, not automated, because virtual audio devices are flaky under automation.
- Acceptance corpus is three fixed clips: a vocal song with full accompaniment, movie dialogue over score, and game capture with dialogue plus effects over score; each is judged Vocal-intelligible plus Music-reduced plus SFX-kept.
- Live criteria: toggle AB shows no pop, loudness parity between ON and OFF, delay subjectively in sync, and headphone unplug plus replug recovers without restart.
- DRM-protected sources that go silent under loopback are recorded as known limitations, not failures.

## Out of Scope

- macOS, Linux, mobile, or browser-extension-only variants.
- Microphone denoising, echo cancellation, or processing of voice-chat input.
- Offline file conversion, batch libraries, or playlist rendering.
- Cloud inference, account sync, or any networked processing.
- Custom signed audio driver or in-engine APO effect.
- Perfect Music silence with zero Vocal loss; v1 explicitly trades residue for instant operation.
- DRM circumvention for sources that block loopback capture.
- Per-app selective filtering, per-tab filtering, or recording the filtered stream.
- Automatic lyric transcription, karaoke scoring, or stem export.

## Further Notes

- Instant plus high quality plus CPU-only is physically contradictory; this spec locks instant plus CPU-only and accepts lower separation quality as the deliberate trade.
- Biggest risks are DRM silence on some streaming apps, exclusive-mode apps bypassing the virtual output, and sample-rate mismatches causing drift; setup guidance must call these out.
- Future directions after v1: optional GPU high-quality path, per-process loopback selection on newer Windows builds, and a true APO or virtual driver to remove the cable dependency.
