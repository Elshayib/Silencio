# 05: Setup plus robustness

**What to build:** Guided first-run setup and everyday robustness: admin install of the virtual output, Default Playback selection, exclusive-mode off guidance, persisted toggle with auto-start, device-change recovery, and honest messaging for sources that block loopback capture.

**Blocked by:** 01 System passthrough with gapless toggle.

**Status:** ready-for-agent

- [x] Fresh machine completes setup and routes all playback through the tool after reboot and app restart
- [x] Toggle state persists across restarts and the tool starts automatically
- [x] Blocked-capture sources are reported as known limitations, not crashes

## Comments

Implemented via `src/silencio/setup.py` (virtual-output detection,
`build_setup_plan` six-step first-run plan, `format_setup_plan`,
`is_admin` with `SILENCIO_ASSUME_ADMIN` override, `KNOWN_LIMITATIONS`),
`src/silencio/startup.py` (Windows Startup-folder `Silencio.bat`
launcher, `startup_entry_path`/`set_auto_start`/`is_auto_start_enabled`
round-trip, persisted toggle restored via `ToggleStateStore`), and
`src/silencio/capture.py` (`BlockedCaptureMonitor` silence counter with
`blocks_to_flag`, `format_blocked_message` honest DRM/exclusive-mode
guidance); `AudioGraph` hardened (`observe_input` defensive, never
raises, `capture_status`, `on_device_change` resets engine ramp plus
monitor and flags reopen, live callback observes input before render).
CLI: `--setup` guided plan, `--install-startup`/`--remove-startup`
(with `--startup-path` for offline exercise), `--diagnose` toggle plus
auto-start plus 74.0ms latency plus known limitations.

- Fresh setup: 6-step plan (admin, virtual-output install, Default
  Playback, exclusive-mode off, apps restarted, reboot); cable found
  by name (`CABLE Output (VB-Audio Virtual Cable)`), unknown hardware
  stays TODO with `--list-devices` guidance.
- Persist plus auto-start: toggle restored ON across `SilencioEngine`
  instances on the same state file; launcher round-trip OFF->ON->OFF
  in tmp dir; `--diagnose` reports both.
- Blocked capture: 4-block monitor flags sustained zeros
  silent->blocked-suspected, sounding block resets to ok; message
  names DRM plus exclusive-mode as a known limitation, never a crash;
  graph `observe_input` swallows malformed driver blocks.
- Device change: `on_device_change` preserves toggle ON, resets
  monitor to ok, flags reopen; `reopen` clears flag; post-recovery
  blocks finite.
- Full suite: 66 passed (55 prior + 11 new), mypy strict clean
  (17 files), `--check` PASS, `--clips` 15/15 PASS.
- Manual live AB still required (per spec, lands in 06): real cable
  install elevated, Default Playback selection, exclusive-mode off,
  reboot plus app restart, headphone unplug plus replug recovery,
  DRM-silence listening check.

## Review disposition (code-review skill, two axes)

- Standards: 0 hard violations (tracker Status/Comments shape,
  canonical triage label, glossary Vocal / Music / SFX, no ADR
  contradiction, tests under tests/). 3 weak smells acknowledged,
  not changed: `cli.py` entry-resolve triplication (one-line shape,
  extracting a helper adds indirection for no new behaviour),
  `build_setup_plan` bool clump (checklist flags are the spec
  friction list verbatim; a bundle type would obscure the six
  named steps), `observe_input` delegation (deliberate crash-barrier,
  not a Middle Man to cut).
- Spec gaps deferred to manual AB / ticket 06, not this one:
  fresh-machine routing action, auto-start launch observation,
  live `capture_status` surfacing in `--diagnose`, MMNotification
  hook wiring (`--run` polls `needs_reopen`; nothing sets it live
  yet). The spec itself orders this: "System graph behavior ...
  is verified manually via live AB, not automated."
- `--diagnose` backend/latency/local-only lines are reused context
  from tickets 03/04 plus ADR-0003, not new behaviour or scope
  creep; `SILENCIO_ASSUME_ADMIN`, `--startup-path`, and the
  PortAudio probe keep setup testable offline.
- Fixed in review: `find_virtual_output` now skips
  microphone-like names via the ticket 03 output-only guard
  (render-path-only scope); `observe_input` now swallows any
  driver exception, not just `ValueError` ("not crashes").
- Contested and kept: monitor reset on device change (new
  endpoint means fresh silence history), 94-block default
  threshold (~2s at 1024 frames), portable `python -m silencio
  --run` launcher target (absolute-interpreter hardening
  deferred; v1 accepts setup friction), guidance-only `--setup`
  (no confirmation flags; API callers can reach `passed=True`,
  CLI honestly reports TODO until the manual steps are done).
