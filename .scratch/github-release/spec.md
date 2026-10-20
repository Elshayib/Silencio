# GitHub distribution and updates

Publish the existing project to Elshayib/Silencio. The owner initially asked
for private source, then explicitly chose public source and public downloads.
Build a Windows x64 installer on version tags and let installed users check,
download and install newer versions without losing their preferences.

Implementation: `.github/workflows/release.yml`, `scripts/set_version.py`,
`scripts/publish_release.py`, `src/silencio/updates.py`, desktop UI and
Inno Setup graceful shutdown. Details: `docs/RELEASING.md`.

The updater ships first in 0.2.0-rc.3; older installs need one manual upgrade.
The existing unsigned RC and hardware validation limitations remain.
