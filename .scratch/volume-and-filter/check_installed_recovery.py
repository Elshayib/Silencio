"""Controlled installed-app crash check; restores mute and restarts the app.

Run only as an explicit local recovery test. Terminates the verified installed
renderer, never unrelated processes. Opens no audio stream or microphone.
"""
import os
from pathlib import Path
import subprocess
import time

from silencio.graph import default_state_path
from silencio.runtime import read_runtime
from silencio.windows_audio import WindowsAudio


def wait_for(predicate, description, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError(description)


def check():
    state = default_state_path()
    installed = Path(os.environ['LOCALAPPDATA']) / 'Programs/Silencio/Silencio.exe'
    runtime = read_runtime(state)
    assert runtime and runtime['running']
    pid = int(runtime['pid'])
    path = subprocess.check_output(['powershell', '-NoProfile', '-Command',
        f'(Get-Process -Id {pid}).Path'], text=True).strip()
    assert Path(path) == installed, 'Only the installed test renderer may be stopped'
    audio = WindowsAudio()
    controls = []
    terminated = False
    original = None
    try:
        endpoints = audio.endpoints()
        cable_endpoint = next(e for e in endpoints if e.is_cable)
        assert audio.default() == cable_endpoint.id
        import sounddevice as sd
        output_name = sd.query_devices(runtime['output_device'])['name']
        output_endpoint = next(e for e in endpoints if e.name == output_name)
        cable = audio.endpoint_volume(cable_endpoint.id)
        controls.append(cable)
        output = audio.endpoint_volume(output_endpoint.id)
        controls.append(output)
        original = cable.read()
        cable.set_mute(True)
        wait_for(lambda: output.read().muted, 'Speaker mute did not arrive')
        import json
        wait_for(lambda: json.loads(state.with_suffix('.routing.json').read_text())
                 .get('volume', {}).get('muted') is True, 'Mute not persisted')
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], check=True, capture_output=True)
        terminated = True
        wait_for(lambda: audio.default() == output_endpoint.id and not state.with_suffix('.routing.json').exists(),
                 'Guardian did not restore speakers')
        assert output.read().muted, 'Crash recovery lost mute'
        assert not state.with_suffix('.routing.json').exists(), 'Recovery journal retained'
        print('PASS: independent guardian restored playback and preserved mute', flush=True)
    finally:
        try:
            try:
                if terminated:
                    subprocess.Popen([str(installed), '--background'], creationflags=subprocess.CREATE_NO_WINDOW)
                    wait_for(lambda: (current := read_runtime(state)) and current.get('running')
                             and current['pid'] != pid, 'Installed app did not restart', 15)
            finally:
                if original is not None:
                    for control in controls:
                        control.set_level(original.level)
                        control.set_mute(original.muted or original.level == 0)
                    print(f'Restored listening setting: {original}', flush=True)
        finally:
            for control in controls:
                control.close()
            audio.close()


if __name__ == '__main__':
    check()
