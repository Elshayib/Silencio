# Windows releases

The desktop distribution is a per-user Inno Setup installer containing a
PyInstaller directory bundle. All audio processing dependencies, native DLLs,
models, driver files, and notices are local. The app itself runs unelevated;
only VB-CABLE installation requests elevation. Driver setup is never retried
against an existing driver, and never forces a reboot.

The desktop restores ordinary playback when it cannot keep the filter running
and displays an unavailable/error state. This deliberately differs from
ADR-0004's earlier fail-silent policy at the application lifecycle boundary:
processing exceptions still mute the current callback, but stopped/crashed
applications must not leave users with a silent Windows output. Normal audio
can therefore contain Music during recovery. Saved ON is never reported as
an active filter while the audio graph is stopped.

## GitHub releases and installed updates

Source and downloads are public at https://github.com/Elshayib/Silencio.
The `Windows release` workflow runs on every `v*` tag and can also be run
manually to build a downloadable Actions artifact without publishing a release.
Only `vMAJOR.MINOR.PATCH` and `vMAJOR.MINOR.PATCH-rc.N` are valid release tags.
The tag stamps Python metadata, the app's version, EXE resources and installer
version together before the build starts.

To release a new version after committing the intended source:

```powershell
git tag v0.2.0-rc.4
git push origin v0.2.0-rc.4
```

Use an unused version number. The workflow runs the complete test suite,
strict type checking and the frozen native/model self-test, then uploads the
installer and its SHA-256 checksum. A release stays in draft until GitHub's
uploaded asset digest matches the locally built EXE. Failed uploads can be
retried; already published binaries cannot be replaced by the workflow.
RC tags publish GitHub prereleases; stable tags publish stable releases.
No long-lived publishing token is needed: the job uses `GITHUB_TOKEN` with
`contents: write`. The licensed driver assertion is based on the owner's
existing redistribution agreement, just as in local builds.

The updater first ships in 0.2.0-rc.3. Users of earlier builds must install a
new installer once. Thereafter the app checks at startup and every 24 hours
while running, or on **Check for updates**. It offers updates without interrupting
audio and only downloads/opens Setup after the user agrees. Setup requests
graceful shutdown before replacing files, preserves per-user preferences,
reuses the existing driver and offers to restart the app when finished.
Network failures leave the running filter alone. Downloads are bounded and
checked against the asset size and GitHub's SHA-256 digest before execution.
This checks transport integrity; it is not publisher code signing.
Stable installations ignore previews. RC installations accept newer RCs or
stable versions. Discovery examines the latest 100 GitHub releases.

This intentionally extends ADR-0003's original “no network use” policy:
the updater contacts GitHub for release metadata and installer downloads.
Audio processing remains local and works offline; no audio or microphone
data is uploaded. The updater contains no GitHub token.

## Local build

Use Windows x64 and Python 3.13 with Tk. Install the dependencies in a dedicated
environment and install Inno Setup 6.7.3 from its signed official distribution:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r packaging/requirements-build.txt
.venv\Scripts\python -m pip install -e ".[desktop,dev]"
powershell -File scripts/build_windows.ps1 -LicensedDriver -Python .venv\Scripts\python.exe -Iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

`-LicensedDriver` asserts that this distribution is covered by the project
owner's VB-Audio agreement (confirmed 2026-10-15). The driver archive is pinned
by SHA-256 in `packaging/vendor/vbcable-manifest.json`. Preparation verifies
every extracted file and includes the unmodified vendor package. The source
repository stores its manifest, not the vendor binaries. Preserve all required
attribution and any terms specific to the distribution agreement.

Build outputs:

- `dist/Silencio/Silencio.exe`: portable directory bundle (keep its `_internal` folder).
- `dist/Silencio-Setup-0.2.0-rc.3-x64.exe`: installer for end users.
- `build/frozen-self-test.json`: native-library and model verification.
- `build/build-environment.json`: exact Python/package versions for the build.
- `build/licenses`: dependency license texts included by the installer.

The build stops if tests, type checking, native model checks, or compilation
fail. Use a clean dedicated environment for reproducible release builds; the
environment manifest records any local differences.

## Required before a public final release

1. Sign `Silencio.exe`, its uninstaller, and the final installer with the
   publisher's code-signing identity. Verify and timestamp signatures. This
   repository does not contain a signing key. An unsigned RC can trigger
   Windows reputation warnings; do not instruct users to disable protections.
2. On clean Windows 10 and 11 x64 machines with no Python or VB-CABLE, install
   offline, approve driver elevation, reboot, and verify automatic startup,
   routing, Vocal playback, and the microphone's unchanged default.
3. Verify UAC denial offers a usable retry; a disabled existing cable must
   never invoke the vendor installer. Test standard users whose admin approval
   uses a separate account, first-login and subsequent-login behavior.
4. Test speakers, USB headsets, Bluetooth stereo, unplug/replug, sleep/resume,
   HDMI changes, and two endpoints with duplicate friendly names. Duplicate
   names currently fail visibly instead of risking the wrong output.
5. Verify ON/OFF, each profile, tray close/reopen, a second launch, graceful
   Quit, forced termination and playback recovery, update, uninstall, and a
   second Windows user. Uninstall keeps the shared VB-CABLE driver installed
   because other programs may depend on it.
6. Listen to representative material on a low-power CPU. Automated model
   fixtures and software timing are not an acoustic latency or quality claim.
   Apps pinned to other devices, exclusive/DRM paths, and non-stereo endpoints
   remain compatibility limits.

The release remains a release candidate until these checks pass.

## Verification history

### GitHub updater release — 2026-10-20

Tag `v0.2.0-rc.3` completed the public
[Windows release workflow](https://github.com/Elshayib/Silencio/actions/runs/39442898927).
All 178 tests passed, strict mypy passed all 30 source files, the frozen
native/model self-test passed, and Inno Setup built the installer. The workflow
published the EXE only after verifying its GitHub asset digest.

The actual public update endpoint was checked from the development machine:
an older RC discovers rc.3, rc.3 reports up to date, and a stable installation
ignores the prerelease. The updater downloaded the published 75,186,263-byte
installer and verified SHA-256
`15ae6748a18a6d2ce974558ab3e1e6a34ee9381648b6f5cf62147de7b47ea2e7`.
No installer was executed during this download check. The new installer
handoff has compiled successfully but still needs a manual installed-upgrade
check; it does not replace the hardware/driver acceptance checks above.

### Volume repair update — 2026-10-16

`0.2.0-rc.2` adds Windows endpoint volume/mute linking, a final output mute
gate, and volume/mute in the route recovery journal. Installed update,
packaged model self-test, ten native volume checks with suppression ON/OFF,
and controlled crash recovery preserving mute all passed on this laptop.
An 8-second playback check in each mode added no underruns, overruns,
deadline misses, or errors. Full-suite and focused regression evidence is
recorded in [the volume issue](../.scratch/volume-and-filter/issues/01-volume-and-mute.md).
The broader final-release checks above remain outstanding.

### Original desktop release — 2026-10-15

The complete `scripts/build_windows.ps1` pipeline succeeded on the development
PC with Python 3.13.5. This is an unsigned test release, as requested by the
project owner, and is not approved as the final public release.

Verified:

- 142 automated tests passed; mypy passed for all 27 source files.
- Frozen and installed self-tests loaded all three actual speech models,
  Tk, tray/image dependencies, PortAudio, and Windows audio endpoints.
- The final installer installed successfully and registered startup. A second
  launch reused the running renderer. The final window and ON/OFF button were
  checked through the Windows UI.
- Forced termination of the installed renderer restored all three playback
  default roles in approximately 0.12 seconds. Microphone defaults were unchanged.
- Uninstall testing on the preceding build closed the running app, restored
  playback, removed the executable and startup entry, and retained the shared
  VB-CABLE driver. The final build changes only concurrent JSON writes and
  redundant UI redraws; its installer/uninstall configuration is unchanged.
- A simultaneous-launch regression test reproduced a shared temporary-file
  collision; unique temporary files fixed it. Stable UI states now avoid
  redundant redraws while diagnostics continue updating.

**Audio stability is still a public-release blocker.** In the final installed
30-second-per-mode fixture check, OFF added no underruns or deadline misses;
ON added one underrun and three processing deadline misses. Its maximum
observed moving-average processing time was 5.98 ms, with 147.7 ms estimated
total delay. An earlier 16-second installed check added three underruns; a
16-second source check was clean. The strict zero-underrun check therefore
failed. UI redraw reduction did not establish a complete fix, and Windows
being locked did not explain all failures. No change was made to the approved
speech model or suppression processing to conceal this limitation.

The driver was already installed on this PC. Fresh driver installation,
permission denial, reboot/first-login behavior, and other audio hardware are
unverified. Test these on clean Windows machines before public distribution.

Local evidence is under `.scratch/release-validation/`, including
`final-installed-self-test.json`, `final-installed-lifecycle.json`,
`uninstall-result.json`, and `final-unlocked-playback.json`. The build log is
`.scratch/release-tools/final-build.log`. These generated files are ignored by
Git. The installer has a sibling `.exe.sha256` checksum file in `dist`.
