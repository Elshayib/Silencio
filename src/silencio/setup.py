"""Guided first-run setup for ticket 05 (offline, no hardware).

Pure helpers around the virtual-cable loopback chain (ADR-0001): detect
the virtual output by device name, report admin rights, and render the
guided plan (admin install, virtual-output install, Default Playback
selection, exclusive-mode off, app restart, reboot). No WASAPI calls
here; the live graph stays manual per the spec because virtual audio
devices are flaky under automation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_CABLE_PATTERNS: tuple[str, ...] = ("cable", "vb-audio", "voicemeeter", "virtual", "silencio")

KNOWN_LIMITATIONS: str = (
    "Known limitations (not failures): DRM-protected sources may go silent "
    "under loopback capture, and exclusive-mode apps bypass the virtual "
    "output. Both are recorded, never crashes."
)


def find_virtual_output(device_names: list[str]) -> str | None:
    """Return the first virtual-output device name, or None when absent.

    Render-path-only scope (ADR-0003): microphone-like names are never
    suggested as the virtual output, even when they contain a cable
    token such as "virtual".
    """
    from silencio.live import ensure_output_only_input

    for name in device_names:
        lowered = str(name).lower()
        if any(token in lowered for token in _CABLE_PATTERNS):
            try:
                ensure_output_only_input(str(name))
            except ValueError:
                continue
            return str(name)
    return None


def is_admin() -> bool:
    """Report whether the process runs with admin rights.

    ``SILENCIO_ASSUME_ADMIN=1`` forces True and ``=0`` forces False so
    setup guidance stays testable without elevation.
    """
    override = os.environ.get("SILENCIO_ASSUME_ADMIN", "").strip()
    if override == "1":
        return True
    if override == "0":
        return False
    try:
        import ctypes  # noqa: I001

        shell32 = getattr(ctypes, "windll", None)
        is_admin_fn = getattr(getattr(shell32, "shell32", None), "IsUserAnAdmin", None)
        if callable(is_admin_fn):
            return bool(is_admin_fn())
    except Exception:
        pass
    return False


@dataclass(frozen=True)
class SetupStep:
    """One first-run action with its completion flag."""

    name: str
    detail: str
    done: bool


@dataclass(frozen=True)
class SetupPlan:
    """The six first-run actions from the spec friction list."""

    steps: tuple[SetupStep, ...] = field(default_factory=tuple)
    cable_name: str | None = None

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.done for s in self.steps)


def build_setup_plan(
    device_names: list[str] | None = None,
    admin: bool | None = None,
    default_is_cable: bool = False,
    exclusive_off: bool = False,
    apps_restarted: bool = False,
    rebooted: bool = False,
) -> SetupPlan:
    """Build the guided first-run plan from offline-observable inputs.

    ``device_names`` is the PortAudio device list (``None`` means unknown
    hardware: cable steps stay TODO with guidance to run --list-devices).
    ``admin=None`` probes :func:`is_admin`. The Default Playback,
    exclusive-mode, restart, and reboot flags are user-confirmed because
    Windows exposes no scriptable query for them in v1.
    """
    names = list(device_names) if device_names is not None else []
    cable = find_virtual_output(names) if device_names is not None else None
    elevated = bool(is_admin()) if admin is None else bool(admin)
    default_done = bool(default_is_cable) and cable is not None
    steps = (
        SetupStep(
            "admin rights",
            "Run setup elevated so the virtual output can install.",
            elevated,
        ),
        SetupStep(
            "virtual output installed",
            "Install the VB-Cable/VoiceMeeter-style virtual output."
            if cable is None
            else f"Found virtual output: {cable}.",
            cable is not None,
        ),
        SetupStep(
            "Default Playback is virtual output",
            "Set the virtual output as Default Playback in Windows Sound.",
            default_done,
        ),
        SetupStep(
            "exclusive-mode off on virtual output",
            "Disable exclusive-mode on the virtual output so apps cannot bypass it.",
            bool(exclusive_off),
        ),
        SetupStep(
            "apps restarted after setup",
            "Restart playback apps so they pick up the new Default Playback.",
            bool(apps_restarted),
        ),
        SetupStep(
            "reboot completed",
            "Reboot after the virtual-output install, then start the tool.",
            bool(rebooted),
        ),
    )
    return SetupPlan(steps=steps, cable_name=cable)


def format_setup_plan(plan: SetupPlan) -> str:
    """Render the plan for the terminal guided setup."""
    lines = ["Silencio first-run setup (virtual output = Default Playback)"]
    for step in plan.steps:
        mark = "PASS" if step.done else "TODO"
        lines.append(f"  [{mark}] {step.name}: {step.detail}")
    if not plan.passed:
        lines.append("Next: install the virtual output elevated, set it as Default")
        lines.append("Playback, turn exclusive-mode off, reboot, restart apps,")
        lines.append("then run with the cable loopback as input and real speakers out.")
    lines.append(KNOWN_LIMITATIONS)
    return "\n".join(lines)
