# 01: Forward Windows volume and mute to the real output

Status: ready-for-human

Implementation, installation and machine verification are complete; retained
for the user's listening check. No implementation dependency remains.

## Reproduction

`python scripts/check_live_volume.py` against installed rc.1 failed:
Windows volume 0%, physical speaker volume 86.216%, physical mute false.
Before the probe, cable volume was 2% and physical speakers 86.216%.
The script restores the settings and plays/records no audio.

Three regression tests against `DesktopRuntime.start_audio` also failed:
speaker level ignored cable level, zero stayed audible, and mute stayed audible.

## Cause and changes

VB-CABLE controls and the physical speaker controls were independent. The
desktop changed default routing without forwarding volume/mute. VolumeLink
now mirrors Windows scalar controls, uses the hardware's own volume curve,
reflects physical control changes, preserves state across output/profile
restarts, and explicitly mutes at zero. A final render gate silences even
already queued frames independently of filter ON/OFF. The CLI shares the link.
COM runs on the control thread, with 50ms polling; telemetry stays throttled.
The routing journal also stores changes to volume/mute. Crash recovery sets
the recovered level and mute before selecting a fallback speaker, while
respecting a user who explicitly changed Windows' default away from the cable.

## Verification

The full suite passed 155 tests before the reconnect and recovery additions;
the final focused desktop, volume, and callback suite passed all 48 tests.
Strict mypy passed all 28 source files. The source desktop passed ten native
Windows checks covering descending levels, zero, mute and unmute with the
filter both ON and OFF.

Installed `0.2.0-rc.2` without restarting Windows. The installed build passed
the same ten native control checks. A controlled termination of its verified
renderer confirmed that the independent guardian restored physical playback
while preserving mute; the app was restarted and the original 2% / unmuted
listening setting restored. The packaged self-test passed all three models.

The final installed 8-second-per-mode playback check added zero underruns,
overruns, processing deadline misses, or errors. Peak smoothed processing was
0.10 ms OFF and 4.66 ms ON; reported total delay stayed 84.7 / 147.7 ms.
These are software/device checks, not an acoustic latency or all-hardware
guarantee. Evidence: [live volume](../live-volume-report.txt),
[live playback](../live-playback-report.json).
