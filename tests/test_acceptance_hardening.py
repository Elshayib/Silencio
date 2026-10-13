"""Ticket 06 acceptance hardening at the single engine buffer seam.

Seam: mixed stereo PCM block in -> Vocal-plus-SFX stereo PCM block out,
via ``run_v1_acceptance`` (live-wired engine plus soak plus
device-change recovery). Live WASAPI/tray/hotkey/driver behaviour stays
manual per the spec; this suite proves the automatable shippability
gates offline: three-clip live AB, gapless loudness-matched toggling,
and a stability soak with device change plus documented limitations.

Vocabulary per GLOSSARY.md: Vocal / Music / SFX.
"""

from __future__ import annotations

import pytest

from silencio.acceptance import V1Check, V1Config, V1Report, run_v1_acceptance


@pytest.fixture(scope="module")
def v1_report() -> V1Report:
    return run_v1_acceptance(V1Config(soak_seconds=2.0))


def _check_by_name(report: V1Report, name: str) -> V1Check:
    for check in report.checks:
        if check.name == name:
            return check
    raise AssertionError(f"missing check {name!r}")


def test_v1_three_clips_keep_vocal_reduce_music_live_ab(v1_report: V1Report) -> None:
    for name in (
        "song live AB Vocal kept Music reduced",
        "movie live AB Vocal kept Music reduced",
        "game live AB Vocal kept Music reduced",
    ):
        assert _check_by_name(v1_report, name).passed


def test_v1_game_sfx_kept_with_imaging(v1_report: V1Report) -> None:
    for name in ("game SFX transients kept", "game SFX imaging kept"):
        assert _check_by_name(v1_report, name).passed


def test_v1_music_includes_crowd_and_fail_open_holds(v1_report: V1Report) -> None:
    for name in ("crowd/choir treated as Music", "ambiguous unison fails open toward Vocal"):
        assert _check_by_name(v1_report, name).passed


def test_v1_toggle_off_bit_perfect_all_sources(v1_report: V1Report) -> None:
    assert _check_by_name(v1_report, "toggle OFF bit-perfect on all sources").passed


def test_v1_toggle_gapless_no_pops_with_loudness_parity(v1_report: V1Report) -> None:
    for name in ("toggle AB gapless with no pops", "toggle AB loudness parity ON vs OFF"):
        assert _check_by_name(v1_report, name).passed


def test_v1_stability_soak_with_device_change_completes(v1_report: V1Report) -> None:
    for name in (
        "stability soak glitch-free on CPU",
        "measured delay inside 150ms budget",
        "device change recovers without restart",
    ):
        assert _check_by_name(v1_report, name).passed


def test_v1_local_only_output_only_scope_holds(v1_report: V1Report) -> None:
    assert _check_by_name(v1_report, "local-only output-only scope holds").passed


def test_v1_known_limitations_documented_as_limitations(v1_report: V1Report) -> None:
    from silencio.acceptance import format_v1_report

    assert _check_by_name(v1_report, "known limitations documented").passed
    assert len(v1_report.known_limitations) >= 1
    joined = " ".join(v1_report.known_limitations).lower()
    assert "drm" in joined
    assert "exclusive-mode" in joined
    rendered = format_v1_report(v1_report)
    assert "known limitation" in rendered.lower()


def test_v1_report_renders_for_shippability_record(v1_report: V1Report) -> None:
    from silencio.acceptance import format_v1_report

    assert v1_report.passed
    assert len(v1_report.checks) >= 11
    rendered = format_v1_report(v1_report)
    assert "PASS" in rendered
    assert "FAIL" not in rendered
    assert "Manual live AB still required" in rendered


def test_v1_acceptance_cli_wires_backend_offline(capsys: pytest.CaptureFixture[str]) -> None:
    from silencio.cli import main

    code = main(["--acceptance", "--backend", "cpu", "--soak-seconds", "2.0"])
    assert code == 0
    out = capsys.readouterr().out.lower()
    assert "v1 acceptance" in out
    assert "known limitation" in out
