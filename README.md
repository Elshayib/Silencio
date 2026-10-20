# Silencio

Local Windows Music suppression for **spoken dialogue**. The default now
uses a trained streaming speech model (DPDFNet), with independent left/right
processing. It prioritizes spoken Vocal; singing and SFX can be removed.
Music overlapping speech can still remain. No filter can promise perfect
isolation with zero delay on every recording.

## Windows app

Download the Windows x64 Setup EXE from [GitHub Releases](https://github.com/Elshayib/Silencio/releases).
This release candidate
includes Python, native audio libraries, all three models, and the licensed
VB-CABLE driver. No terminal, pip, account, or runtime download is needed.
It targets Windows 10 (1809+) and Windows 11 on x64 hardware.

Setup installs and launches the desktop app. If VB-CABLE is missing, approve
Windows' administrator prompt and restart Windows after driver installation.
Silencio then starts at sign-in, chooses connected speakers, and configures
default playback after its audio streams are ready. Existing VB-CABLE installs
are reused. Your microphone's default is preserved across driver installation.

The window has an ON/OFF button, output selection, and three filter choices.
Closing it keeps the app in the tray. **Ctrl+Alt+M** toggles suppression.
**Quit** restores normal playback; a separate recovery process also restores
playback after a crash. Settings and the last ON/OFF choice survive restarts.
Disable **Start with Windows** in the app to launch it yourself instead.

Starting with **0.2.0-rc.3**, installed copies check GitHub for updates at startup
and daily while running. **Check for updates** also checks immediately.
Choose **Install update** to download a verified installer; Setup closes the
app safely and preserves preferences. Earlier copies need this installer
installed once manually to gain the updater. Stable releases ignore release
candidates; release candidates can update to newer previews or stable releases.
Update requests send no audio, microphone data, or account credentials.

Version tags such as `v0.2.0-rc.3` automatically test, build, and publish the EXE
through GitHub Actions. See [release instructions](docs/RELEASING.md).

Windows volume, media keys, and mute control the selected speakers through
Silencio. Zero volume is silent with suppression ON or OFF, including audio
already queued for playback. The app retains volume and mute when changing
profile, switching output, or reconnecting; Quit leaves the current listening
level in place. **Ctrl+Alt+M toggles filtering, not sound mute.**
If you enabled VB-CABLE's optional **Windows Volume Control** in its own
control panel, it can attenuate a second time before the filter; leave that
option disabled when using Silencio's speaker-volume link.

This build is unsigned and needs clean-machine driver/reboot testing before
it can be called a final public release. See [release checks](docs/RELEASING.md).

## Run from source

Install dependencies once, then double-click **Start-Silencio.cmd**, or run:

```powershell
python -m pip install -e ".[desktop]"
python -m silencio.desktop
```

All three verified model files ship with the project. Audio stays on this laptop;
the live filter requires no network, account, PyTorch, or discrete GPU.
Missing dependencies or a damaged model produce an error rather than a
silent fallback to the old filter.

## Audio routing and compatibility

The desktop app handles default playback automatically. Applications pinned
to another sound device or using exclusive/protected audio can bypass the
Windows default route. If one app is unaffected, select **Default** in that
app's output settings and restart playback.

The advanced `python -m silencio --run` CLI retains manual routing. For it,
VB-CABLE must already be installed. In Windows Sound settings:

1. Set **CABLE Input** as default playback.
2. Send browsers and other applications to **Default** or **CABLE Input**
   in the volume mixer. Applications routed to real speakers bypass Silencio.
   Restart playback after changing the route.
3. Disable **Listen to this device** on **CABLE Output**, which otherwise
   plays the original Music alongside filtered audio.
4. Use shared mode; disable exclusive-mode bypass. The live bridge supports
   44.1, 48, 88.2, 96, 176.4, and 192 kHz stereo playback devices.

Silencio reads **CABLE Output**, converts its native sample rate continuously,
and renders to real speakers. Microphone inputs are rejected. Switch Windows
default playback back to real speakers after quitting the CLI; toggling OFF while
Silencio runs restores the original mix through the engine.

## Profiles

The desired target is instruments only: clapping, cheering, and other audience
sounds should be retained. The current speech models cannot reliably make that
distinction. Strong Music removal remains the priority, so the default is not
weakened by mixing rejected sound back in. See the
[model investigation](.scratch/volume-and-filter/filter-research.md) for the
replacement candidates and remaining live-performance requirements.

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
# Checks the running app's volume/mute controls without playing or recording:
python scripts/check_live_volume.py
```

Diagnostics show the actual running profile, backend, delay estimate,
processing time, deadline misses, and audio underruns/overruns. A saved ON
flag is distinct from a running filter. `--on`, `--off` and `--toggle`
control the live process within half a second. Duplicate renderers using
the same state file are refused. Desktop logs are bounded files in
`%LOCALAPPDATA%\Silencio\logs`, accessible with **Open logs**. They contain
diagnostics, not recorded audio. Preferences and recovery journals live in
`%APPDATA%\Silencio`.

The evaluation compares the old and new engines using recorded dialogue,
recorded Music, a known mixture, and a centered changing instrumental probe.
It aligns each engine's actual delay and measures both suppression and Vocal
distortion, plus CPU timings on the current machine. Run timing checks without
other tests in parallel. Fixture results do not certify all languages,
sources, headphones or perceptual lip-sync. The older `--clips`, `--soak`
and `--acceptance` commands cover the legacy spectral profiles.

Model attribution and checksums: [models](src/silencio/models/README.md).
Test audio attribution: [fixtures](tests/fixtures/LICENSE.md).
