"""Verify the running desktop's Windows volume/mute link without playing audio.

Temporarily lowers cable volume and toggles mute; restores both endpoints.
No audio is recorded and no microphone is opened.
"""
from __future__ import annotations

import time

from silencio.windows_audio import WindowsAudio


def check() -> None:
    audio = WindowsAudio()
    cable = speakers = None
    original_cable = original_speakers = None
    store = None
    original_enabled = None
    try:
        endpoints = audio.endpoints()
        source = next(e for e in endpoints if e.is_cable and e.id == audio.default())
        # Resolve the actual output selected by the running desktop.
        import sounddevice as sd
        from silencio.graph import default_state_path
        from silencio.runtime import read_runtime
        from silencio.state import ToggleStateStore
        runtime = read_runtime(default_state_path())
        assert runtime and runtime['running'], 'Start the desktop app first'
        name = sd.query_devices(runtime['output_device'])['name']
        target = next(e for e in endpoints if e.name == name and not e.is_virtual)
        cable, speakers = audio.endpoint_volume(source.id), audio.endpoint_volume(target.id)
        original_cable, original_speakers = cable.read(), speakers.read()
        store = ToggleStateStore(default_state_path())
        original_enabled = store.load()
        for enabled in (False, True):
            store.save(enabled)
            deadline = time.monotonic() + 3
            while True:
                current = read_runtime(default_state_path())
                if current and current['enabled'] == enabled:
                    break
                assert time.monotonic() < deadline, 'Filter toggle did not reach the desktop'
                time.sleep(.025)
            for level, muted in ((.02, False), (.01, False), (0.0, False), (.01, True), (.02, False)):
                cable.set_mute(True)
                cable.set_level(level)
                cable.set_mute(muted)
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    actual = speakers.read()
                    if abs(actual.level - level) < .005 and actual.muted == (muted or level == 0):
                        break
                    time.sleep(.025)
                print(f'Filter={enabled}, Windows slider={level:.0%}, mute={muted}: speakers={actual}', flush=True)
                assert abs(actual.level - level) < .005, 'Windows volume did not reach the speakers'
                assert actual.muted == (muted or level == 0), 'Zero volume/mute must silence the speakers'
    finally:
        if store is not None and original_enabled is not None:
            store.save(original_enabled)
        if cable and speakers and original_cable and original_speakers:
            # Restore the source first, allow a running link to observe it,
            # then restore the physical endpoint to its original setting.
            for control, original in ((cable, original_cable), (speakers, original_speakers)):
                control.set_mute(True)
                control.set_level(original.level)
                control.set_mute(original.muted)
                time.sleep(.15)
        if cable:
            cable.close()
        if speakers:
            speakers.close()
        audio.close()


if __name__ == '__main__':
    check()
