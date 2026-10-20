from __future__ import annotations

import hashlib
import io
from pathlib import Path
import runpy

import pytest

from silencio import updates
from silencio.updates import Update, download_update, select_update
from silencio.version import RELEASE_REPOSITORY

PAYLOAD = b"test installer payload"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def release(version: str, **extra):
    filename = f"Silencio-Setup-{version}-x64.exe"
    return dict(tag_name=f"v{version}", draft=False, prerelease="-rc." in version,
                assets=[dict(name=filename, state="uploaded", size=len(PAYLOAD),
                             digest=f"sha256:{DIGEST}", browser_download_url=(
                                 f"https://github.com/{RELEASE_REPOSITORY}/releases/download/v{version}/{filename}"))],
                **extra)


def test_version_ordering_channels_and_no_downgrade():
    releases = [release("0.2.0-rc.10"), release("0.2.0-rc.3"), release("0.2.0"), release("0.3.0-rc.1")]
    assert select_update(releases, "0.2.0rc2").version == "0.3.0-rc.1"
    assert select_update(releases, "0.1.0").version == "0.2.0"
    assert select_update(releases, "0.2.0") is None
    assert select_update(releases, "1.0.0") is None
    assert select_update([release("0.2.0-rc.10"), release("0.2.0-rc.3")], "0.2.0rc2").version == "0.2.0-rc.10"
    assert select_update([release("0.2.0")], "0.2.0rc3").version == "0.2.0"


def test_drafts_and_unrelated_assets_are_not_installable():
    draft = release("2.0.0")
    draft["draft"] = True
    wrong_platform = release("3.0.0")
    wrong_platform["assets"][0]["name"] = "Silencio-arm64.exe"
    assert select_update([draft, wrong_platform], "1.0.0") is None


@pytest.mark.parametrize("field,value", [
    ("digest", None), ("digest", "sha256:123"), ("size", -1), ("size", True),
    ("size", updates.MAX_INSTALLER_BYTES + 1), ("state", "new"),
    ("browser_download_url", "http://github.com/installer.exe"),
    ("browser_download_url", "https://example.com/installer.exe"),
])
def test_invalid_asset_is_rejected(field, value):
    candidate = release("1.0.0")
    candidate["assets"][0][field] = value
    with pytest.raises(ValueError):
        select_update([candidate], "0.1.0")


class Response(io.BytesIO):
    def geturl(self):
        return "https://release-assets.githubusercontent.com/redirected-asset"


@pytest.mark.parametrize("payload", [PAYLOAD, PAYLOAD[:-1], PAYLOAD + b"x", b"X" * len(PAYLOAD)])
def test_download_verifies_exact_size_and_hash_and_cleans_failures(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **kw: Response(payload))
    update = select_update([release("1.0.0")], "0.1.0")
    if payload == PAYLOAD:
        path = download_update(update, tmp_path)
        assert path.read_bytes() == PAYLOAD
        assert path.suffix == ".exe"
    else:
        with pytest.raises(ValueError):
            download_update(update, tmp_path)
        assert list(tmp_path.iterdir()) == []


def test_download_does_not_follow_untrusted_initial_url(tmp_path):
    update = Update("1.0.0", "https://example.com/payload.exe", DIGEST, len(PAYLOAD))
    with pytest.raises(ValueError, match="location"):
        download_update(update, tmp_path)


def test_check_response_is_bounded(monkeypatch):
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda *a, **kw: Response(b"x" * (updates.MAX_METADATA_BYTES + 1)))
    with pytest.raises(ValueError, match="too large"):
        updates.check_for_update()


def test_metadata_and_download_use_no_authentication(monkeypatch, tmp_path):
    import json
    requests = []

    def open_request(request, **kw):
        requests.append(request)
        return Response(json.dumps([release("99.0.0")]).encode() if len(requests) == 1 else PAYLOAD)

    monkeypatch.setattr(updates.urllib.request, "urlopen", open_request)
    download_update(updates.check_for_update(), tmp_path)
    assert len(requests) == 2
    assert all("Authorization" not in request.headers for request in requests)


def test_tag_stamps_all_version_fields(tmp_path):
    import shutil
    root = Path(__file__).resolve().parents[1]
    for relative in ["src/silencio/version.py", "packaging/version.txt", "pyproject.toml"]:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, destination)
    stamp = runpy.run_path(str(root / "scripts/set_version.py"))["stamp"]
    stamp("v1.2.3-rc.4", tmp_path)
    assert 'VERSION = "1.2.3rc4"' in (tmp_path / "src/silencio/version.py").read_text()
    assert 'version = "1.2.3rc4"' in (tmp_path / "pyproject.toml").read_text()
    assert 'WindowsVersion "1.2.3.4"' in (tmp_path / "packaging/version.iss").read_text()
    assert "filevers=(1, 2, 3, 4)" in (tmp_path / "packaging/version.txt").read_text()
    stamp("v1.2.3", tmp_path)
    assert "flags=0x0" in (tmp_path / "packaging/version.txt").read_text()
    for invalid in ["v1.2", "bad", "v1.2.3-rc.0", "v999999.0.0", "v01.2.3"]:
        with pytest.raises(ValueError):
            stamp(invalid, tmp_path)


@pytest.mark.parametrize("digest_ok", [True, False])
def test_release_is_not_published_until_uploaded_digest_matches(tmp_path, monkeypatch, digest_ok):
    import json
    import importlib.util
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("publish_release", root / "scripts/publish_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("RELEASE_TAG", "v1.2.3-rc.4")
    monkeypatch.setenv("GH_REPO", RELEASE_REPOSITORY)
    (tmp_path / "dist").mkdir()
    (tmp_path / "build").mkdir()
    name = "Silencio-Setup-1.2.3-rc.4-x64.exe"
    (tmp_path / "dist" / name).write_bytes(PAYLOAD)
    (tmp_path / "dist" / (name + ".sha256")).write_text(f"{DIGEST}  {name}\n")
    calls = []

    def gh(*args):
        calls.append(args)
        if args[0] == "api":
            return "[[]]"
        if args[:2] == ("release", "view"):
            return json.dumps({"assets": [{"name": name, "digest": "sha256:" + (DIGEST if digest_ok else "0" * 64)}]})
        return ""

    monkeypatch.setattr(module, "gh", gh)
    if digest_ok:
        module.main()
        assert calls[-1] == ("release", "edit", "v1.2.3-rc.4", "--draft=false", "--latest=false")
    else:
        with pytest.raises(RuntimeError, match="remains a draft"):
            module.main()
        assert not any(call[:2] == ("release", "edit") for call in calls)
    assert "--draft" in next(call for call in calls if call[:2] == ("release", "create"))
