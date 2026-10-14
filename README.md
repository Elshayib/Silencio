# Silencio

Local Windows Music suppression for **spoken dialogue**. The default now
uses a trained streaming speech model (DPDFNet), with independent left/right
processing. It prioritizes spoken Vocal; singing and SFX can be removed.
Music overlapping speech can still remain. No filter can promise perfect
isolation with zero delay on every recording.

## Start

Double-click **Start-Silencio.cmd**. It starts ON with the speech profile
and tray controls. **Ctrl+Alt+M** or the tray menu toggles suppression;
**Quit** stops it. Install dependencies once if needed:

```powershell
python -m pip install -e ".[audio,tray,speech]"
```

All three verified model files ship with the project. Audio stays on this laptop;
the live filter requires no network, account, PyTorch, or discrete GPU.
Missing dependencies or a damaged model produce an error rather than a
silent fallback to the old filter.

## Audio routing

VB-Cable must already be installed. In Windows Sound settings:

1. Set **CABLE Input** as default playback.
2. Send browsers and other applications to **Default** or **CABLE Input**
   in the volume mixer. Applications routed to real speakers bypass Silencio.
   Restart playback after changing the route.
3. Disable **Listen to this device** on **CABLE Output**, which otherwise
   plays the original Music alongside filtered audio.
4. Use 44.1 kHz or 48 kHz shared mode; disable exclusive-mode bypass.

Silencio reads **CABLE Output**, converts its native sample rate continuously,
and renders to real speakers. Microphone inputs are rejected. Switch Windows
default playback back to real speakers after quitting; toggling OFF while
Silencio runs restores the original mix through the engine.

## Profiles

- **speech** (default): DPDFNet baseline, selected for this laptop's balance
  of dialogue extraction and CPU headroom; 63 ms processing-pipeline delay.
- **speech-quality**: DPDFNet2, stronger residual suppression with higher CPU
  demand; also 63 ms pipeline delay. This laptop showed more live dropouts
  with this model, so it is not the default.
- **speech-fast**: GTCRN with residual suppression, lower CPU demand and
  34 ms pipeline delay. Use when gaming or other work leaves less CPU headroom.
- **aggressive**: previous spectral filter. It can miss centered instruments.
- **balanced**: previous Vocal/SFX-preserving filter; more Music remains.

Quit the existing instance before changing profile:

```powershell
python -m silencio --run --on --profile speech-fast --backend cpu --tray
```

For `speech-fast`, `--speech-strength 1` favors clarity; the default `2`
cuts more residue and `3` is harsher. This setting applies only to speech-fast.
Model delay excludes audio-device and bridge buffering. The live diagnostic
reports their combined estimate, not an acoustic latency measurement.
Queues are bounded so latency cannot grow indefinitely.
After sustained exact digital silence the model sleeps to save CPU; it
resumes automatically. This does not use a volume threshold that clips quiet Vocal.

The default preserves consonant detail with a compensated output conversion
filter. It also restores small waveform differences where the model closely
agrees with the original Vocal; rejected Music receives no restoration. The
same model and input preprocessing still make the suppression decisions.

OFF suspends neural processing completely and passes the original mix.
The live cable/speaker connection uses band-limited sample-rate conversion
and a bounded frame buffer. Short fades soften missing/discarded audio if
Windows misses a callback, and the bridge refills before resuming. These
fades contain clicks; they cannot reconstruct audio lost by a driver.

## Diagnostics and verification

```powershell
python -m silencio --diagnose
python -m silencio --list-devices
python -m pip install -e ".[audio,tray,speech,dev]"
python -m pytest -q
python scripts/evaluate_speech.py --output .scratch/speech-report.json
# Plays a quiet known fixture through the running cable route, ON and OFF:
python scripts/check_live_playback.py
```

Diagnostics show the actual running profile, backend, delay estimate,
processing time, deadline misses, and audio underruns/overruns. A saved ON
flag is distinct from a running filter. `--on`, `--off` and `--toggle`
control the live process within half a second. Duplicate renderers using
the same state file are refused. Logs are `.scratch/live.log` and
`.scratch/live-errors.log`; they contain diagnostics, not recorded audio.

The evaluation compares the old and new engines using recorded dialogue,
recorded Music, a known mixture, and a centered changing instrumental probe.
It aligns each engine's actual delay and measures both suppression and Vocal
distortion, plus CPU timings on the current machine. Run timing checks without
other tests in parallel. Fixture results do not certify all languages,
sources, headphones or perceptual lip-sync. The older `--clips`, `--soak`
and `--acceptance` commands cover the legacy spectral profiles.

Model attribution and checksums: [models](src/silencio/models/README.md).
Test audio attribution: [fixtures](tests/fixtures/LICENSE.md).
