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

Verification: `v0.2.0-rc.3` published through GitHub Actions run 39442898927.
178 tests, strict mypy and frozen model self-test passed. Public discovery,
RC/stable channel selection, and actual installer download/hash verification
passed. No local installation was changed. See the release verification
history for remaining manual acceptance checks.
