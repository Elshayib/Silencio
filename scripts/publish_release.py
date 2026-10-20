"""Publish only verified installer outputs; keep incomplete uploads in drafts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True).strip()


def main() -> None:
    tag = os.environ["RELEASE_TAG"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-rc\.\d+)?", tag):
        raise ValueError("Invalid release tag")
    name = f"Silencio-Setup-{tag[1:]}-x64.exe"
    installer = ROOT / "dist" / name
    checksum = installer.with_suffix(".exe.sha256")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    if checksum.read_text(encoding="utf-8-sig").strip() != f"{digest}  {name}":
        raise ValueError("Installer checksum does not match")
    # Query list (instead of interpreting a failed API call as 'not found').
    releases = json.loads(gh("api", "--paginate", "--slurp",
                             f"repos/{os.environ['GH_REPO']}/releases?per_page=100"))
    existing = next((item for page in releases for item in page if item["tag_name"] == tag), None)
    if existing and not existing["draft"]:
        raise RuntimeError("Release is already published. Push a new version tag; published binaries are never replaced.")
    if not existing:
        notes = ROOT / "build/release-notes.md"
        notes.write_text(
            f"Silencio {tag[1:]} for Windows x64.\n\n"
            "Download the Setup EXE below. Existing installations can use **Check for updates**.\n\n"
            "This installer is currently unsigned. Windows may display a publisher/reputation warning. "
            "Code signing and the full hardware acceptance matrix are still pending. "
            "See docs/RELEASING.md in the source repository for validation limits.\n\n"
            "Audio processing stays on your device. Update checks contact GitHub; no audio is uploaded.\n",
            encoding="utf-8")
        args = ["release", "create", tag, "--verify-tag", "--draft", "--title", f"Silencio {tag[1:]}",
                "--notes-file", str(notes)]
        if "-rc." in tag:
            args.append("--prerelease")
        gh(*args)
    gh("release", "upload", tag, str(installer), str(checksum), "--clobber")
    release = json.loads(gh("release", "view", tag, "--json", "assets"))
    asset = next(item for item in release["assets"] if item["name"] == name)
    if asset.get("digest") != f"sha256:{digest}":
        raise RuntimeError("GitHub asset digest did not match; release remains a draft")
    gh("release", "edit", tag, "--draft=false", "--latest=false" if "-rc." in tag else "--latest")


if __name__ == "__main__":
    main()
