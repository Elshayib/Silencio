# 01: System passthrough with gapless toggle

**What to build:** System-wide audio path with no separation yet: virtual output as Default Playback, loopback capture rendered to real speakers bit-perfect, with tray plus hotkey toggle that switches gaplessly and survives headphone unplug and replug.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Any playback source (browser, movie, game, song) is audible through the tool with no loss when toggle is OFF
- [ ] Flipping toggle mid-sound produces no pop or click and switches in under 50ms
- [ ] Unplugging and replugging headphones recovers without restart
