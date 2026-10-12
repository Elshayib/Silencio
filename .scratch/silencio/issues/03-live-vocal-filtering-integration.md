# 03: Live Vocal filtering integration

**What to build:** Live wiring of the separator engine into the system path so toggle ON emits Vocal plus SFX with Music reduced across any playback source, toggle OFF restores the original mix bit-perfect with loudness parity, fully local-only with microphone inputs untouched.

**Blocked by:** 01 System passthrough with gapless toggle, 02 Separator engine at buffer seam with clip harness.

**Status:** ready-for-agent

- [ ] Live browser, movie, game, and song playback all filter when ON and restore when OFF
- [ ] Teammate speech arriving over speakers is preserved as Vocal while own microphone input is untouched
- [ ] No audio upload occurs and end-to-end feel stays in sync at or under 150ms
