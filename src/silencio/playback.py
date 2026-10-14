"""Bounded stereo bridge with short fades around missing/discarded audio.

Independent Windows endpoint clocks deliver callbacks in bursts. A frame
buffer handles partial blocks without dropping a whole packet; a 2 ms fade
contains discontinuities if Windows still misses a deadline. Normal audio
is copied unchanged. No inference or file access happens here.
"""
from __future__ import annotations

from threading import Lock

import numpy as np

from silencio.engine import Float32Stereo


class PlaybackBridge:
    def __init__(self, block_frames: int, sample_rate: int) -> None:
        self.capacity = 4 * block_frames
        self._target = 2 * block_frames
        self._buffer = np.zeros((self.capacity, 2), np.float32)
        self._read = 0
        self._size = 0
        self._priming = True
        self._discontinuous = True
        self._fade_samples = max(1, round(sample_rate * .002))
        self._fade_left = 0
        self._anchor = np.zeros(2, np.float32)
        self._last = np.zeros(2, np.float32)
        self._lock = Lock()
        self.underruns = 0
        self.overruns = 0

    def push(self, block: Float32Stereo) -> None:
        with self._lock:
            if len(block) > self.capacity:
                block = block[-self.capacity:]
                self._discontinuous = True
            overflow = max(0, self._size + len(block) - self.capacity)
            if overflow:
                self._read = (self._read + overflow) % self.capacity
                self._size -= overflow
                self.overruns += 1
                self._discontinuous = True
            write = (self._read + self._size) % self.capacity
            first = min(len(block), self.capacity - write)
            self._buffer[write:write + first] = block[:first]
            self._buffer[:len(block) - first] = block[first:]
            self._size += len(block)

    def render(self, out: Float32Stereo) -> None:
        out.fill(0)
        with self._lock:
            if self._priming and self._size < self._target:
                return
            self._priming = False
            count = min(len(out), self._size)
            first = min(count, self.capacity - self._read)
            out[:first] = self._buffer[self._read:self._read + first]
            out[first:count] = self._buffer[:count - first]
            self._read = (self._read + count) % self.capacity
            self._size -= count
            discontinuous = self._discontinuous
            self._discontinuous = False
            if count < len(out):
                self.underruns += 1
                self._priming = True
                self._discontinuous = True

        # Render-only state: interpolate over a discontinuity, never over
        # ordinary block boundaries. Both channels use the same fade timing.
        if discontinuous:
            self._anchor[:] = self._last
            self._fade_left = self._fade_samples
        if self._fade_left:
            fade = min(count, self._fade_left)
            weights = (np.arange(fade) + self._fade_samples - self._fade_left + 1) / self._fade_samples
            out[:fade] = self._anchor * (1 - weights[:, None]) + out[:fade] * weights[:, None]
            self._fade_left -= fade
        if count < len(out):
            if count:
                start = max(0, count - self._fade_samples)
                fade = min(self._fade_samples, len(out) - start)
                # Even a one-frame remainder needs a full fade. Extend its
                # last value into the missing region instead of making a step.
                if start + fade > count:
                    out[count:start + fade] = out[count - 1]
                out[start:start + fade] *= np.linspace(1, 0, fade)[:, None]
            else:
                fade = min(len(out), self._fade_samples)
                out[:fade] = self._last * np.linspace(1, 0, fade)[:, None]
            self._fade_left = 0
        self._last[:] = out[-1]
