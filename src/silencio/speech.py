"""Local streaming speech extraction with pinned CPU neural models.

The fast MIT-licensed GTCRN model uses a 32 ms window / 16 ms hop at 16 kHz.
Independent recurrent states preserve left/right Vocal without a destructive
mono downmix. Band-limited conversion, overlap-add and block adaptation add
34 ms of fixed pipeline delay at the engine's 48 kHz stereo seam. The default
DPDFNet models add 63 ms including their internal delay. No audio uploads,
model downloads, file I/O, or session creation occur in process_block().
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from silencio.engine import Float32Stereo, SAMPLE_RATE

MODEL_PATH = Path(__file__).with_name("models") / "dpdfnet_baseline.onnx"
DPDF_SHA256 = "debaf0e8893479fca91b8b4c1eae8db195aa8980ccc9012f5809fde2b738151a"
QUALITY_MODEL_PATH = Path(__file__).with_name("models") / "dpdfnet2.onnx"
QUALITY_SHA256 = "ce35d6025fc71df0ef10d1540e1b7916837bbfe5f6896deb744508d2cad487a9"
FAST_MODEL_PATH = Path(__file__).with_name("models") / "gtcrn.onnx"
MODEL_SHA256 = "b4718df6228e7bdf1a8a435cf98f838636eb2fd331acabf86ba87c5192ebcb87"
HOP = 256
FRAME = 512
BLOCK = HOP * 3
FILTER_TAPS = 97
SYNTHESIS_TAPS = 193
FAST_LATENCY_SAMPLES = BLOCK * 2 + FILTER_TAPS - 1
# Both DPDFNet recurrent exports add four hops (40 ms) inside the model.
# Confirmed by waveform correlation against clean recorded speech; do not
# report only the outer STFT/adapter delay as end-to-end latency.
LATENCY_SAMPLES = 480 * 6 + (FILTER_TAPS + SYNTHESIS_TAPS - 2) // 2


class _VocalDetail:
    """Restore small waveform details only where the model agrees with input.

    The aligned residual must be below 2.5% of the accepted Vocal energy.
    Rejected Music therefore gets no dry signal. Decisions are independent
    per channel, have no level gate, and add no delay beyond the neural path.
    """

    def __init__(self, delay: int) -> None:
        self._delay = delay
        self.reset()

    def reset(self) -> None:
        self._history = np.zeros((self._delay, 2), np.float32)
        self._weight = np.zeros(2)

    def process(self, source: Float32Stereo, clean: Float32Stereo) -> Float32Stereo:
        buffered = np.concatenate((self._history, source))
        aligned = buffered[:len(source)]
        self._history = buffered[len(source):].copy()
        residual = aligned.astype(np.float64) - clean
        error = np.mean(residual * residual, axis=0)
        energy = np.mean(clean.astype(np.float64) ** 2, axis=0)
        confidence = np.clip(1 - error / (.025 * energy + 1e-20), 0, 1) ** 2
        target = .8 * confidence
        following = np.minimum(target, self._weight + .15)
        weights = np.linspace(self._weight, following, len(source))
        # Never carry restoration over into a newly rejected Music frame.
        weights = np.minimum(weights, target)
        self._weight = following
        return np.asarray(clean + residual * weights, dtype=np.float32)


class _SpeechStream:
    """Fixed-storage block adaptation and band-limited 48/16 kHz conversion."""
    sample_rate = SAMPLE_RATE
    num_channels = 2
    block_size = BLOCK

    def _configure_conversion(self) -> None:
        try:
            from scipy.signal import firwin, lfilter
        except ImportError as exc:
            raise RuntimeError('Speech filtering needs: python -m pip install -e ".[speech]"') from exc
        self._lfilter = lfilter
        self._fir = firwin(FILTER_TAPS, 7200, fs=SAMPLE_RATE, window=("kaiser", 8.0))

    def _reset_buffers(self) -> None:
        self._down_state = np.zeros((FILTER_TAPS - 1, 2))
        self._up_state = np.zeros((FILTER_TAPS - 1, 2))
        self._input = np.zeros((self.block_size, 2), np.float32)
        self._output = np.zeros((self.block_size, 2), np.float32)
        self._position = 0
        self._quiet_hops = 0

    def __call__(self, mixed: Float32Stereo) -> Float32Stereo:
        return self.process_block(mixed)

    def process_block(self, mixed: Float32Stereo) -> Float32Stereo:
        arr = np.asarray(mixed, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != 2 or not len(arr):
            raise ValueError("expected non-empty stereo block (frames, 2)")
        if not np.all(np.isfinite(arr)):
            raise ValueError("input contains non-finite audio")
        out = np.empty_like(arr)
        offset = 0
        # Fixed storage and identical hop boundaries for any driver block size.
        while offset < len(arr):
            count = min(self.block_size - self._position, len(arr) - offset)
            stop = self._position + count
            out[offset:offset + count] = self._output[self._position:stop]
            self._input[self._position:stop] = arr[offset:offset + count]
            self._position = stop
            offset += count
            if self._position == self.block_size:
                hop = self._input
                if not np.any(hop):
                    self._quiet_hops += 1
                    if self._quiet_hops > 12:
                        # Only exact digital silence qualifies. Drain more than
                        # the model's full tail first; never gate quiet Vocal.
                        self._output.fill(0)
                    else:
                        self._output[:] = self._process_hop(hop)
                else:
                    if self._quiet_hops > 12:
                        # Clear stale recurrent context on playback resume,
                        # retaining the already collected hop in this local.
                        self.reset()
                    self._quiet_hops = 0
                    self._output[:] = self._process_hop(hop)
                self._position = 0
        return out

    def _process_hop(self, block: Float32Stereo) -> Float32Stereo:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError


def _verify_model(path: Path, digest: str) -> None:
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Bundled speech model is missing or damaged; reinstall Silencio. No fallback to unfiltered Music.")


class FastSpeechSeparator(_SpeechStream):
    """GTCRN with residual suppression; strength 1..3 trades clarity for cuts."""

    latency_samples = FAST_LATENCY_SAMPLES
    backend_name = "GTCRN ONNX / CPU (stereo speech)"

    def __init__(self, strength: float = 2.0) -> None:
        if not np.isfinite(strength) or not 1.0 <= strength <= 3.0:
            raise ValueError("speech strength must be between 1 and 3")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError('Speech filtering needs: python -m pip install -e ".[speech]"') from exc
        _verify_model(FAST_MODEL_PATH, MODEL_SHA256)
        self._configure_conversion()
        self._strength = float(strength)
        self._window = np.sqrt(np.hanning(FRAME + 1)[:-1])[:, None]
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self._session = ort.InferenceSession(str(FAST_MODEL_PATH), options, providers=["CPUExecutionProvider"])
        self._state_shapes = {v.name: v.shape for v in self._session.get_inputs()[1:]}
        self.reset()
        for _ in range(3):
            self._process_hop(np.zeros((BLOCK, 2), dtype=np.float32))
        self.reset()

    def reset(self) -> None:
        self._states: list[dict[str, Any]] = [
            {name: np.zeros(shape, np.float32) for name, shape in self._state_shapes.items()}
            for _ in range(2)
        ]
        self._previous = np.zeros((HOP, 2))
        self._overlap = np.zeros((HOP, 2))
        self._reset_buffers()

    def _process_hop(self, block: Float32Stereo) -> Float32Stereo:
        filtered, self._down_state = self._lfilter(
            self._fir, [1.0], block, axis=0, zi=self._down_state)
        current = filtered[::3]
        frame = np.concatenate((self._previous, current))
        self._previous[:] = current
        spectrum = np.fft.rfft(frame * self._window, axis=0)
        enhanced = np.empty_like(spectrum)
        features = np.empty((1, FRAME // 2 + 1, 1, 2), np.float32)
        for channel in range(2):
            spec = spectrum[:, channel]
            features[0, :, 0, 0] = spec.real
            features[0, :, 0, 1] = spec.imag
            predicted, *states = self._session.run(None, {"mix": features, **self._states[channel]})
            self._states[channel] = dict(zip(self._state_shapes, states))
            clean = predicted[0, :, 0, 0] + 1j * predicted[0, :, 0, 1]
            # Further reduce bins the learned model already identifies as
            # interference. Never mix the original signal back into ON audio.
            if self._strength > 1.0:
                mask = np.minimum(np.abs(clean) / (np.abs(spec) + 1e-8), 1.0)
                clean *= mask ** (self._strength - 1.0)
            enhanced[:, channel] = clean
        recovered = np.fft.irfft(enhanced, n=FRAME, axis=0) * self._window
        low_rate = recovered[:HOP] + self._overlap
        self._overlap[:] = recovered[HOP:]
        expanded = np.zeros((BLOCK, 2))
        expanded[::3] = low_rate
        result, self._up_state = self._lfilter(
            self._fir * 3.0, [1.0], expanded, axis=0, zi=self._up_state)
        return np.asarray(result, dtype=np.float32)


class SpeechSeparator(_SpeechStream):
    """DPDFNet: stereo dialogue extraction, 63 ms fixed pipeline delay."""

    block_size = 480
    latency_samples = LATENCY_SAMPLES
    backend_name = "DPDFNet baseline ONNX / CPU (stereo speech)"

    def __init__(self, high_quality: bool = False, preserve_detail: bool = True) -> None:
        try:
            import sherpa_onnx as sherpa
        except ImportError as exc:
            raise RuntimeError('Speech filtering needs: python -m pip install -e ".[speech]"') from exc
        model = QUALITY_MODEL_PATH if high_quality else MODEL_PATH
        _verify_model(model, QUALITY_SHA256 if high_quality else DPDF_SHA256)
        if high_quality:
            self.backend_name = "DPDFNet2 ONNX / CPU (stereo speech)"
        self._configure_conversion()
        from scipy.signal import firwin2, freqz
        # Keep model input and Music decisions unchanged. The longer output
        # filter restores the converter's roll-off in accepted consonants,
        # tapering to zero before 8 kHz instead of boosting the whole signal.
        frequencies = np.array([0, 1000, 4000, 5500, 6000, 6500, 6800, 7000, 7200])
        _, response = freqz(self._fir, worN=frequencies, fs=SAMPLE_RATE)
        self._synthesis_fir = firwin2(
            SYNTHESIS_TAPS, np.r_[frequencies, 7400, 7600, 8000, 24000],
            np.r_[1 / np.abs(response), 1, .2, 0, 0], fs=SAMPLE_RATE, window=("kaiser", 8.0))
        self._detail = _VocalDetail(self.latency_samples - self.block_size) if preserve_detail else None
        config = sherpa.OnlineSpeechDenoiserConfig(
            model=sherpa.OfflineSpeechDenoiserModelConfig(
                dpdfnet=sherpa.OfflineSpeechDenoiserDpdfNetModelConfig(model=str(model)),
                num_threads=1, provider="cpu"))
        if not config.validate():
            raise RuntimeError("Invalid bundled speech model configuration")
        self._denoisers = [sherpa.OnlineSpeechDenoiser(config) for _ in range(2)]
        self.reset()
        for _ in range(3):
            self._process_hop(np.zeros((self.block_size, 2), np.float32))
        self.reset()

    def reset(self) -> None:
        for denoiser in self._denoisers:
            denoiser.reset()
        self._reset_buffers()
        self._up_state = np.zeros((SYNTHESIS_TAPS - 1, 2))
        if self._detail is not None:
            self._detail.reset()

    def _process_hop(self, block: Float32Stereo) -> Float32Stereo:
        filtered, self._down_state = self._lfilter(
            self._fir, [1.0], block, axis=0, zi=self._down_state)
        expanded = np.zeros((self.block_size, 2))
        for channel, denoiser in enumerate(self._denoisers):
            mono = np.ascontiguousarray(filtered[::3, channel], dtype=np.float32)
            clean = np.asarray(denoiser.run(mono, 16000).samples, dtype=np.float32)
            if len(clean) == 160:
                expanded[::3, channel] = clean
            elif len(clean) != 0:
                raise RuntimeError(f"Unexpected speech model output size: {len(clean)}")
        result, self._up_state = self._lfilter(
            self._synthesis_fir * 3.0, [1.0], expanded, axis=0, zi=self._up_state)
        clean = np.asarray(result, dtype=np.float32)
        return self._detail.process(block, clean) if self._detail is not None else clean
