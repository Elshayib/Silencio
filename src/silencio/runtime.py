"""Single live instance and a small, local health report (no captured audio)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, BinaryIO

from silencio.state import replace_with_retry


class LiveInstance:
    def __init__(self, state_path: Path) -> None:
        self.path = state_path.with_suffix(".live.lock")
        self._file: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError:
            stream.close()
            return False
        self._file = stream
        return True

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def write_runtime(state_path: Path, data: dict[str, Any]) -> bool:
    """Best-effort heartbeat: diagnostics must never terminate live audio."""
    path = state_path.with_suffix(".runtime.json")
    payload = dict(data, pid=os.getpid(), updated_at=time.time())
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        replace_with_retry(temporary, path)
        return True
    except OSError:
        # Keep the last complete report; the next control-loop tick retries.
        return False


def read_runtime(state_path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(state_path.with_suffix(".runtime.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or time.time() - float(data["updated_at"]) > 3:
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None
