"""Diagnostic readers must never be able to crash a live audio process."""
from silencio.runtime import write_runtime, read_runtime


def test_busy_runtime_file_does_not_stop_audio_control_loop(monkeypatch, tmp_path):
    path = tmp_path / 'state.json'
    write_runtime(path, dict(running=True,enabled=True))
    def locked(*args):
        raise PermissionError('Windows reader holds the destination open')
    monkeypatch.setattr('silencio.runtime.os.replace',locked)
    assert write_runtime(path,dict(running=True,enabled=True)) is False
    assert read_runtime(path)['running']


def test_runtime_recovers_after_transient_windows_lock(monkeypatch, tmp_path):
    import os
    path = tmp_path / 'state.json'
    replace = os.replace
    calls = 0
    def intermittent(source,destination):
        nonlocal calls
        calls+=1
        if calls==1:
            raise PermissionError('reader is closing the file')
        replace(source,destination)
    monkeypatch.setattr('silencio.runtime.os.replace',intermittent)
    assert write_runtime(path,dict(running=True)) is True
    assert read_runtime(path)['running']
