"""Stamp every Windows version field from vMAJOR.MINOR.PATCH[-rc.N]."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def stamp(tag: str, root: Path = ROOT) -> None:
    match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.([1-9]\d*))?", tag)
    if not match:
        raise ValueError("Use vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N")
    major, minor, patch = (int(match[i]) for i in (1, 2, 3))
    rc = int(match[4] or 0)
    if any(value > 65535 for value in (major, minor, patch, rc)):
        raise ValueError("Windows version components must fit in 16 bits")
    display = tag[1:]
    python_version = f"{major}.{minor}.{patch}" + (f"rc{rc}" if rc else "")
    identity = root / "src/silencio/version.py"
    identity.write_text(re.sub(r'(?m)^(VERSION|RELEASE_VERSION) = .+$',
        lambda m: f'{m[1]} = "{python_version if m[1] == "VERSION" else display}"',
        identity.read_text(encoding="utf-8")), encoding="utf-8")
    project = root / "pyproject.toml"
    project.write_text(re.sub(r'(?m)^version = ".+"$', f'version = "{python_version}"',
                             project.read_text(encoding="utf-8")), encoding="utf-8")
    (root / "packaging/version.iss").write_text(
        f'#define AppVersion "{display}"\n#define WindowsVersion "{major}.{minor}.{patch}.{rc}"\n',
        encoding="utf-8")
    version_file = root / "packaging/version.txt"
    contents = version_file.read_text(encoding="utf-8")
    contents = re.sub(r"(filevers|prodvers)=\([^)]*\)",
                      lambda m: f"{m[1]}=({major}, {minor}, {patch}, {rc})", contents)
    contents = re.sub(r"(StringStruct\('(?:FileVersion|ProductVersion)', ')[^']+",
                      lambda m: m[1] + display, contents)
    contents = re.sub(r"flags=0x[0-9a-f]+", "flags=0x2" if rc else "flags=0x0", contents)
    version_file.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    stamp(parser.parse_args().tag)
