"""Verify/download the licensed driver; gather notices from the build environment."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ["numpy", "scipy", "onnxruntime", "sherpa-onnx", "sherpa-onnx-core",
            "sounddevice", "pystray", "pillow", "keyboard", "cffi", "pycparser",
            "six", "flatbuffers", "packaging", "protobuf", "pyinstaller",
            "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--licensed-driver", action="store_true",
                        help="confirm this build is covered by your VB-Audio distribution agreement")
    args = parser.parse_args()
    if not args.licensed_driver:
        parser.error("Bundling VB-CABLE requires a distribution agreement; pass --licensed-driver when authorized.")
    vendor = ROOT / "packaging/vendor"
    manifest = json.loads((vendor / "vbcable-manifest.json").read_text())
    directory = vendor / "vbcable"
    if not directory.exists():
        archive = ROOT / "build/VBCABLE_Driver_Pack45.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(manifest["url"], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
            raise RuntimeError("Driver download checksum mismatch; refusing to package it.")
        with zipfile.ZipFile(archive) as bundle:
            if set(bundle.namelist()) != set(manifest["files"]):
                raise RuntimeError("Unexpected driver archive contents.")
            bundle.extractall(directory)
    for name, expected in manifest["files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Driver integrity check failed: {name}")
    licenses = ROOT / "build/licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name in PACKAGES:
        package = metadata.distribution(name)
        versions[name] = package.version
        destination = licenses / name
        destination.mkdir(exist_ok=True)
        copied = 0
        for relative in package.files or []:
            if any(token in relative.name.upper() for token in ("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT")):
                source = Path(package.locate_file(relative))
                if source.is_file() and source.suffix.lower() not in (".py", ".pyc", ".pyd", ".dll"):
                    output = destination / str(relative).replace("/", "_").replace("\\", "_")
                    shutil.copyfile(source, output)
                    copied += 1
        # Preserve metadata even for packages embedding their notice there.
        (destination / "METADATA.txt").write_text(package.read_text("METADATA") or "", encoding="utf-8")
        if not copied:
            if name in ("sherpa-onnx-core", "flatbuffers"):
                shutil.copyfile(ROOT / "src/silencio/models/DPDFNET-LICENSE.txt", destination / "Apache-2.0.txt")
            else:
                raise RuntimeError(f"Missing redistributable license text for {name}")
    python_root = Path(sys.base_prefix)
    for source in [python_root / "LICENSE.txt", *python_root.glob("tcl/*/license.terms")]:
        if source.is_file():
            shutil.copyfile(source, licenses / (source.parent.name + "-" + source.name))
    (ROOT / "build/build-environment.json").write_text(json.dumps(
        {"python": sys.version, "packages": versions, "driver_archive_sha256": manifest["archive_sha256"]}, indent=2), encoding="utf-8")
    print("Verified VB-CABLE and collected third-party notices.")


if __name__ == "__main__":
    main()
