"""Full v1 acceptance run proving shippability (ticket 06).

Offline deterministic proof at the single engine buffer seam: mixed
stereo PCM block in, Vocal-plus-SFX stereo PCM block out. The run wires
the ticket 04 boosted live engine (the same backend ``--run`` starts,
CPU floor with GPU boost when present) through the ticket 02
acceptance clips, then adds the ticket 06 gates on top: three-clip
live AB with Vocal kept and Music reduced plus SFX kept, gapless
loudness-matched toggle AB, and a stability soak with device-change
recovery. Sources that block loopback capture stay documented known
limitations, never failures.

System graph behaviour (loopback capture to speaker render, hotkey
toggle, device replug feel) stays manual per the spec because virtual
audio devices are flaky under automation; this module proves every
automatable share at the seam and prints the manual-AB record.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from silencio.boost import build_boosted_live_engine
from silencio.capture import BLOCKED_MESSAGE
from silencio.clips import (
    GAME_BLIP_S,
    GAME_SCORE_GAP_S,
    MOVIE_SCORE_GAP_S,
    make_crowd_clip,
    make_game_clip,
    make_movie_clip,
    make_song_clip,
    make_unison_clip,
    run_clip,
)
from silencio.engine import MAX_SWITCH_SAMPLES_50MS, SAMPLE_RATE, SilencioEngine
from silencio.graph import AudioGraph, GraphConfig
from silencio.live import estimate_end_to_end_ms
from silencio.metrics import bandpower, correlation, db, lr_ratio_db, total_power
from silencio.setup import KNOWN_LIMITATIONS
from silencio.soak import SoakConfig, SoakReport, run_soak

Float32Stereo = NDArray[np.float32]

_BACKENDS: tuple[str, ...] = ("auto", "cpu", "gpu")


@dataclass(frozen=True)
class V1Config:
    """Length and live block size of the v1 acceptance run."""

    block_frames: int = 1024
    ramp_samples: int = 480
    soak_seconds: float = 8.0
    backend: str = "auto"

    def __post_init__(self) -> None:
        if self.block_frames <= 0:
            raise ValueError(f"block_frames must be positive, got {self.block_frames}")
        if not 1 <= self.ramp_samples <= MAX_SWITCH_SAMPLES_50MS:
            raise ValueError(
                f"ramp_samples must be 1..{MAX_SWITCH_SAMPLES_50MS}, got {self.ramp_samples}"
            )
        if self.soak_seconds <= 0.0:
            raise ValueError(f"soak_seconds must be positive, got {self.soak_seconds}")
        if self.backend not in _BACKENDS:
            raise ValueError(f'backend must be one of {_BACKENDS}, got {self.backend!r}')


@dataclass(frozen=True)
class V1Check:
    """One shippability gate with its measured detail."""

    name: str
    detail: str
    passed: bool


@dataclass(frozen=True)
class V1Report:
    """Outcome of one full v1 acceptance run."""

    checks: tuple[V1Check, ...]
    soak: SoakReport | None
    known_limitations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


def _live_on(config: V1Config) -> SilencioEngine:
    return build_boosted_live_engine(
        prefer=config.backend, ramp_samples=config.ramp_samples, enabled=True
    )


def _live_off(config: V1Config) -> SilencioEngine:
    return build_boosted_live_engine(
        prefer=config.backend, ramp_samples=config.ramp_samples, enabled=False
    )


def _song_check(config: V1Config) -> V1Check:
    clip = make_song_clip()
    out, ref = run_clip(_live_on(config), clip, block_frames=config.block_frames)
    vocal_band = db(
        bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0),
        bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0),
    )
    music_out, music_ref = run_clip(_live_on(config), clip, stem="music", block_frames=config.block_frames)
    vocal_out, vocal_ref = run_clip(_live_on(config), clip, stem="vocal", block_frames=config.block_frames)
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    ok = vocal_band >= -3.0 and music_delta <= -4.0 and vocal_delta >= -2.0
    ok = ok and music_delta <= vocal_delta - 2.0
    return V1Check(
        "song live AB Vocal kept Music reduced",
        f"Vocal band {vocal_band:+.1f}dB; Music {music_delta:+.1f}dB vs Vocal {vocal_delta:+.1f}dB",
        bool(ok),
    )


def _movie_check(config: V1Config) -> V1Check:
    clip = make_movie_clip()
    out, ref = run_clip(_live_on(config), clip, block_frames=config.block_frames)
    vocal_band = db(
        bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0),
        bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0),
    )
    music_out, music_ref = run_clip(_live_on(config), clip, stem="music", block_frames=config.block_frames)
    vocal_out, vocal_ref = run_clip(_live_on(config), clip, stem="vocal", block_frames=config.block_frames)
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    gap_lo = int(MOVIE_SCORE_GAP_S[0] * SAMPLE_RATE) - SAMPLE_RATE
    gap_hi = int(MOVIE_SCORE_GAP_S[1] * SAMPLE_RATE) - SAMPLE_RATE
    gap_delta = db(total_power(out[gap_lo:gap_hi]), total_power(ref[gap_lo:gap_hi]))
    ok = vocal_band >= -2.0 and vocal_delta >= -2.0 and music_delta <= -4.0 and gap_delta <= -4.0
    return V1Check(
        "movie live AB Vocal kept Music reduced",
        f"Vocal band {vocal_band:+.1f}dB; Music {music_delta:+.1f}dB vs Vocal {vocal_delta:+.1f}dB; "
        f"gap {gap_delta:+.1f}dB",
        bool(ok),
    )


def _game_check(config: V1Config) -> V1Check:
    clip = make_game_clip()
    out, ref = run_clip(_live_on(config), clip, block_frames=config.block_frames)
    vocal_band = db(
        bandpower(out[:, 0] + out[:, 1], 200.0, 4000.0),
        bandpower(ref[:, 0] + ref[:, 1], 200.0, 4000.0),
    )
    music_out, music_ref = run_clip(_live_on(config), clip, stem="music", block_frames=config.block_frames)
    vocal_out, vocal_ref = run_clip(_live_on(config), clip, stem="vocal", block_frames=config.block_frames)
    music_delta = db(total_power(music_out), total_power(music_ref))
    vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
    gap_lo = int(GAME_SCORE_GAP_S[0] * SAMPLE_RATE) - SAMPLE_RATE
    gap_hi = int(GAME_SCORE_GAP_S[1] * SAMPLE_RATE) - SAMPLE_RATE
    gap_delta = db(total_power(out[gap_lo:gap_hi]), total_power(ref[gap_lo:gap_hi]))
    ok = vocal_band >= -2.0 and vocal_delta >= -2.0 and music_delta <= -4.0 and gap_delta <= -4.0
    ok = ok and music_delta <= vocal_delta - 2.0
    return V1Check(
        "game live AB Vocal kept Music reduced",
        f"Vocal band {vocal_band:+.1f}dB; Music {music_delta:+.1f}dB vs Vocal {vocal_delta:+.1f}dB; "
        f"gap {gap_delta:+.1f}dB",
        bool(ok),
    )


def _sfx_checks(config: V1Config) -> tuple[V1Check, V1Check]:
    clip = make_game_clip()
    assert clip.sfx is not None
    out, _ = run_clip(_live_on(config), clip, block_frames=config.block_frames)
    steady = SAMPLE_RATE
    sfx_steady = clip.sfx[steady : steady + out.shape[0]]
    peak_at = int(np.argmax(np.max(np.abs(sfx_steady), axis=1)))
    peak_in = float(np.max(np.abs(sfx_steady)))
    peak_out = float(np.max(np.abs(out[max(0, peak_at - 64) : peak_at + 64])))
    peak_delta = db(peak_out**2, peak_in**2)
    blip_start = int(GAME_BLIP_S * SAMPLE_RATE)
    blip_region = clip.sfx[blip_start : blip_start + int(0.06 * SAMPLE_RATE)]
    blip_peak = blip_start + int(np.argmax(np.max(np.abs(blip_region), axis=1))) - SAMPLE_RATE
    stem_window = clip.sfx[SAMPLE_RATE + blip_peak - 128 : SAMPLE_RATE + blip_peak + 128]
    out_window = out[blip_peak - 128 : blip_peak + 128]
    stem_lr = lr_ratio_db(stem_window)
    out_lr = lr_ratio_db(out_window)
    span = int(0.06 * SAMPLE_RATE)
    onset_at = int(GAME_BLIP_S * SAMPLE_RATE) - SAMPLE_RATE
    corr = correlation(
        out[onset_at : onset_at + span],
        clip.sfx[SAMPLE_RATE + onset_at : SAMPLE_RATE + onset_at + span],
    )
    return (
        V1Check(
            "game SFX transients kept",
            f"peak {peak_delta:+.1f}dB",
            bool(-3.0 <= peak_delta <= 3.0),
        ),
        V1Check(
            "game SFX imaging kept",
            f"L/R stem {stem_lr:+.1f}dB vs out {out_lr:+.1f}dB; corr {corr:.2f}",
            bool(
                np.sign(out_lr) == np.sign(stem_lr)
                and abs(out_lr - stem_lr) <= 2.5
                and corr >= 0.7
            ),
        ),
    )


def _crowd_check(config: V1Config) -> V1Check:
    clip = make_crowd_clip()
    out, ref = run_clip(_live_on(config), clip, stem="music", block_frames=config.block_frames)
    delta = db(total_power(out), total_power(ref))
    return V1Check(
        "crowd/choir treated as Music",
        f"crowd {delta:+.1f}dB",
        bool(delta <= -4.0),
    )


def _unison_check(config: V1Config) -> V1Check:
    clip = make_unison_clip()
    out, _ = run_clip(_live_on(config), clip, block_frames=config.block_frames)
    _, vocal_ref = run_clip(_live_on(config), clip, stem="vocal", block_frames=config.block_frames)
    delta = db(total_power(out), total_power(vocal_ref))
    return V1Check(
        "ambiguous unison fails open toward Vocal",
        f"mix out vs Vocal {delta:+.1f}dB",
        bool(delta >= -3.0),
    )


def _off_check(config: V1Config) -> V1Check:
    names: list[str] = []
    failed: list[str] = []
    for clip in (make_song_clip(), make_movie_clip(), make_game_clip()):
        engine = _live_off(config)
        outs: list[Float32Stereo] = []
        for start in range(0, clip.mix.shape[0], config.block_frames):
            outs.append(engine.process_block(clip.mix[start : start + config.block_frames]))
        names.append(clip.name)
        if not bool(np.array_equal(np.concatenate(outs, axis=0), clip.mix)):
            failed.append(clip.name)
    detail = "mix untouched on " + "/".join(names) if not failed else "altered: " + ",".join(failed)
    return V1Check("toggle OFF bit-perfect on all sources", detail, not failed)


def _gapless_check(config: V1Config) -> V1Check:
    clip = make_song_clip()
    engine = build_boosted_live_engine(prefer=config.backend, ramp_samples=config.ramp_samples)
    steady = np.concatenate(
        [engine.process_block(clip.mix[i : i + 512]) for i in range(0, 2048, 512)],
        axis=0,
    )
    natural = float(np.max(np.abs(np.diff(steady.astype(np.float64), axis=0))))
    engine.set_enabled(True)
    on_stream = np.concatenate(
        [engine.process_block(clip.mix[i : i + 128]) for i in range(2048, 2048 + 960, 128)],
        axis=0,
    )
    step_on = float(np.max(np.abs(np.diff(on_stream.astype(np.float64), axis=0))))
    engine.set_enabled(False)
    off_stream = np.concatenate(
        [engine.process_block(clip.mix[i : i + 128]) for i in range(3008, 3008 + 960, 128)],
        axis=0,
    )
    step_off = float(np.max(np.abs(np.diff(off_stream.astype(np.float64), axis=0))))
    ok = (
        step_on <= 3.0 * natural + 1e-6
        and step_off <= 3.0 * natural + 1e-6
        and step_on < 0.3
        and step_off < 0.3
        and engine.switch_time_ms < 50.0
    )
    ok = ok and engine.ramp_samples <= MAX_SWITCH_SAMPLES_50MS
    return V1Check(
        "toggle AB gapless with no pops",
        f"ON step {step_on:.4f} OFF step {step_off:.4f} vs natural {natural:.4f}; "
        f"switch {engine.switch_time_ms:.1f}ms",
        bool(ok),
    )


def _parity_check(config: V1Config) -> V1Check:
    parts: list[str] = []
    ok = True
    for clip in (make_song_clip(), make_movie_clip(), make_game_clip()):
        out, ref = run_clip(_live_on(config), clip, block_frames=config.block_frames)
        mix_delta = db(total_power(out), total_power(ref))
        vocal_out, vocal_ref = run_clip(
            _live_on(config), clip, stem="vocal", block_frames=config.block_frames
        )
        vocal_delta = db(total_power(vocal_out), total_power(vocal_ref))
        parts.append(f"{clip.name} mix {mix_delta:+.1f}dB Vocal {vocal_delta:+.1f}dB")
        # ON removes Music so the mix drops by single-digit dB (measured
        # -4.0 on the song clip); the floor below catches a mute, which the
        # one-sided blast cap alone would pass.
        ok = ok and mix_delta <= 1.0 and mix_delta >= -12.0 and -2.0 <= vocal_delta <= 1.0
    return V1Check(
        "toggle AB loudness parity ON vs OFF",
        "; ".join(parts),
        bool(ok),
    )


def _device_check(config: V1Config) -> V1Check:
    engine = build_boosted_live_engine(
        prefer=config.backend, ramp_samples=config.ramp_samples, enabled=True
    )
    graph = AudioGraph(engine, GraphConfig(block_frames=config.block_frames))
    graph.observe_input(np.zeros((config.block_frames, 2), dtype=np.float32))
    graph.on_device_change()
    preserved = engine.enabled is True and graph.needs_reopen is True and graph.capture_status == "ok"
    graph.reopen()
    cleared = graph.needs_reopen is False and engine.enabled is True
    out = engine.process_block(np.zeros((512, 2), dtype=np.float32))
    finite = out.shape == (512, 2) and bool(np.all(np.isfinite(out)))
    return V1Check(
        "device change recovers without restart",
        "toggle preserved, reopen flagged then cleared, post-recovery block finite",
        bool(preserved and cleared and finite),
    )


def _limitations_check() -> V1Check:
    texts = (KNOWN_LIMITATIONS, BLOCKED_MESSAGE)
    ok = all("drm" in text.lower() and "exclusive-mode" in text.lower() for text in texts)
    ok = ok and all("known limitation" in text.lower() for text in texts)
    return V1Check(
        "known limitations documented",
        "DRM silence plus exclusive-mode bypass recorded as limitations, never crashes",
        bool(ok),
    )


def _scope_check() -> V1Check:
    """Local audio scope, with the isolated updater exception in ADR-0007."""
    import re
    from pathlib import Path

    from silencio.live import ensure_output_only_input

    try:
        ensure_output_only_input("Microphone (USB Audio)")
        mic_refused = False
    except ValueError:
        mic_refused = True
    pattern = re.compile(
        r"^\s*(import\s+(socket|urllib|http\.client|requests|websocket)\b"
        r"|from\s+(socket|urllib|http\.client|requests|websocket)\b)",
        re.MULTILINE,
    )
    scanned = 0
    clean = True
    for path in Path(__file__).parent.glob("*.py"):
        if path.name == "updates.py":
            continue  # ADR-0007 permits only metadata/installer networking here.
        scanned += 1
        if pattern.search(path.read_text(encoding="utf-8")) is not None:
            clean = False
    ok = mic_refused and clean and scanned > 0
    return V1Check(
        "local-only output-only scope holds",
        f"mic input refused, {scanned} non-updater modules import no network clients",
        bool(ok),
    )


def run_v1_acceptance(config: V1Config | None = None) -> V1Report:
    """Run every v1 shippability gate through the buffer seam."""
    cfg = config if config is not None else V1Config()
    static_ms = estimate_end_to_end_ms(block_frames=cfg.block_frames, ramp_samples=cfg.ramp_samples)
    checks: list[V1Check] = [
        _song_check(cfg),
        _movie_check(cfg),
        _game_check(cfg),
        *_sfx_checks(cfg),
        _crowd_check(cfg),
        _unison_check(cfg),
        _off_check(cfg),
        _gapless_check(cfg),
        _parity_check(cfg),
    ]
    soak_cfg = SoakConfig(
        duration_s=cfg.soak_seconds,
        block_frames=cfg.block_frames,
        ramp_samples=cfg.ramp_samples,
        toggles=2,
    )
    # The soak leg pins the CPU pass: this check proves the compute floor,
    # whatever backend the clip gates run. The boosted variant is proven
    # separately in ticket 04, which runs the same seam deeper.
    soak = run_soak(
        engine_factory=lambda: build_boosted_live_engine(
            prefer="cpu", ramp_samples=cfg.ramp_samples, enabled=True
        ),
        config=soak_cfg,
    )
    checks.append(
        V1Check(
            "stability soak glitch-free on CPU",
            f"{soak.blocks} blocks, {soak.dropouts} dropouts, RTF {soak.rtf:.2f}, "
            f"max {soak.max_block_ms:.2f}ms vs {soak_cfg.block_ms:.2f}ms budget",
            bool(soak.dropouts == 0 and soak.rtf < 0.5 and soak.max_block_ms < soak_cfg.block_ms),
        )
    )
    checks.append(
        V1Check(
            "measured delay inside 150ms budget",
            f"static {static_ms:.1f}ms + p95 {soak.p95_block_ms:.2f}ms = "
            f"{soak.measured_end_to_end_ms:.1f}ms (budget 150ms)",
            bool(static_ms <= 150.0 and soak.measured_end_to_end_ms <= 150.0 and soak.passed),
        )
    )
    checks.append(_device_check(cfg))
    checks.append(_scope_check())
    checks.append(_limitations_check())
    return V1Report(
        checks=tuple(checks),
        soak=soak,
        known_limitations=(KNOWN_LIMITATIONS, BLOCKED_MESSAGE),
    )


def format_v1_report(report: V1Report) -> str:
    """Render the v1 acceptance outcome for the terminal / shippability record."""
    lines = ["Silencio v1 acceptance (buffer seam, no hardware)"]
    for check in report.checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    if report.soak is not None:
        soak = report.soak
        lines.append(
            f"  soak: {soak.blocks} blocks, {soak.dropouts} dropouts, RTF {soak.rtf:.2f}, "
            f"measured end-to-end {soak.measured_end_to_end_ms:.1f}ms (budget 150ms)"
        )
    lines.append("Known limitations (not failures):")
    for limitation in report.known_limitations:
        lines.append(f"  - {limitation}")
    lines.append("Manual live AB still required: browser/movie/game audible through the cable,")
    lines.append("mid-sound toggle gapless, headphone replug recovery, loudness-parity listening,")
    lines.append("DRM-silence check, driver jitter.")
    return "\n".join(lines)
