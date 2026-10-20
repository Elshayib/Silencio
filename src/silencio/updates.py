"""Public GitHub release discovery and bounded, verified installer downloads.

No account credentials are shipped. Audio is never sent over the network.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Any

from packaging.version import Version

from silencio.version import RELEASE_REPOSITORY, VERSION

MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Update:
    version: str
    url: str
    sha256: str
    size: int


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "User-Agent": f"Silencio/{VERSION}",
        "Accept": "application/vnd.github+json" if url.startswith("https://api.github.com/") else "application/octet-stream",
    })


def select_update(releases: Any, current: str = VERSION) -> Update | None:
    """Stable installs ignore preview releases; preview installs can graduate."""
    installed = Version(current)
    if not isinstance(releases, list):
        raise ValueError("Invalid update response")
    candidates: list[Update] = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name", "")
        if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\.\d+)?", tag):
            continue
        version = Version(tag[1:])
        if version <= installed or (not installed.is_prerelease and
                                    (version.is_prerelease or release.get("prerelease"))):
            continue
        filename = f"Silencio-Setup-{tag[1:]}-x64.exe"
        expected_url = f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{tag}/{filename}"
        for asset in release.get("assets", []):
            if not isinstance(asset, dict) or asset.get("name") != filename:
                continue
            digest = asset.get("digest") or ""
            size = asset.get("size")
            if (asset.get("state") != "uploaded" or asset.get("browser_download_url") != expected_url
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                    or type(size) is not int or not 0 < size <= MAX_INSTALLER_BYTES):
                raise ValueError("The update has incomplete or invalid verification information")
            candidates.append(Update(tag[1:], expected_url, digest[7:], size))
    return max(candidates, key=lambda item: Version(item.version), default=None)


def check_for_update() -> Update | None:
    # Include previews for RC users; use a bounded page instead of /latest,
    # which deliberately excludes GitHub prereleases.
    url = f"https://api.github.com/repos/{RELEASE_REPOSITORY}/releases?per_page=100"
    with urllib.request.urlopen(_request(url), timeout=20) as response:
        payload = response.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError("Update response is too large")
    return select_update(json.loads(payload))


def download_update(update: Update, directory: Path) -> Path:
    """Leave no executable behind on truncation, overflow or checksum failure."""
    if (not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+)?", update.version)
            or not re.fullmatch(r"[0-9a-f]{64}", update.sha256)
            or not 0 < update.size <= MAX_INSTALLER_BYTES):
        raise ValueError("Invalid update")
    filename = f"Silencio-Setup-{update.version}-x64.exe"
    expected_url = f"https://github.com/{RELEASE_REPOSITORY}/releases/download/v{update.version}/{filename}"
    if update.url != expected_url:
        raise ValueError("Unexpected update download location")
    directory.mkdir(parents=True, exist_ok=True)
    # A fresh directory avoids accidentally launching a stale cached installer.
    working = Path(tempfile.mkdtemp(prefix="update-", dir=directory))
    partial = working / "download.part"
    destination = working / filename
    try:
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(_request(update.url), timeout=60) as response, partial.open("xb") as output:
            if not response.geturl().startswith("https://"):
                raise ValueError("Update download requires HTTPS")
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > update.size:
                    raise ValueError("Update download exceeds the expected size")
                digest.update(chunk)
                output.write(chunk)
        if total != update.size or digest.hexdigest() != update.sha256:
            raise ValueError("Update verification failed. Please try again.")
        partial.replace(destination)
        return destination
    except BaseException:
        partial.unlink(missing_ok=True)
        working.rmdir()
        raise


def launch_installer(path: Path) -> None:
    # Interactive, per-user setup. Its PrepareToInstall callback asks the
    # existing app to restore playback and quit before replacing any files.
    subprocess.Popen([os.fspath(path), "/SP-", "/NORESTART"], close_fds=True)
