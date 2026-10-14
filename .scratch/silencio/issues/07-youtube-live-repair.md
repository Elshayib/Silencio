# 07: Live launch, control, routing and stronger Music suppression

Status: ready-for-agent

## Request

YouTube Music remains audible. User prioritizes Music removal and immediate
video sync over Vocal quality. This overrides ADR-0002's fail-open policy for
the new aggressive profile; the balanced profile preserves that policy.

## Findings

- `--run --on` returned after saving ON and never opened a stream.
- External `--on` / `--toggle` writes were ignored by the live graph.
- Device indices bypassed microphone checks; output could feed the cable.
- The separator passed all content above 4kHz at unity.
- Default DirectSound buffers exceeded the claimed hardware delay budget.
- WASAPI cable capture is natively 44100Hz; speakers are natively 48000Hz.
  Forcing automatic input conversion opened the stream but produced too
  few captured frames and many underruns on this pair.

## Implemented

- Live launch flag handling, atomic state persistence and control-thread
  reload, resolved-device checks and feedback refusal.
- Separate native-rate WASAPI streams, continuous vectorized resampling,
  bounded primed bridge, recoverable stopped streams, callback error reporting.
- Default live aggressive profile suppresses stereo/steady content over
  the whole spectrum and removes transient-based bypass. Vocal/SFX damage
  is accepted; overlapping mono instruments can still leak.
- Tray/hotkey controls, duplicate-instance lock, current runtime diagnostics,
  explicit Windows launcher and setup/limitations in README.

## Verification

- Launch/toggle/microphone/feedback regressions reproduced before fixes.
- High-frequency instrumental probe initially measured 0.0dB attenuation.
- New aggressive probes require over 25dB steady instrumental attenuation;
  synthetic song Music requires over 15dB while some Vocal remains.
- Real cable stimulus reached the live graph and measured ~20dB attenuation
  over the complete signal including the attack.
- Real native-rate graph: approximately 105.3ms driver/buffering estimate,
  ~239039 pipeline frames in five seconds, zero processing errors/overruns.
  Several startup underruns were observed; steady listening is still needed.
- Full automated suite and strict typing are run after final changes.

## Comments

The updated filter was launched ON with the aggressive profile and tray on
the user's Windows desktop. Real YouTube listening feedback is pending.
Synthetic acceptance does not establish perfect isolation on arbitrary
recordings, and the hardware delay estimate is not an acoustic measurement.
