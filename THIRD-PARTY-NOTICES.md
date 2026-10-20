# Third-party software

Silencio processes playback locally using the following components. Full
license texts are included in the installed `licenses` directory and with
the models and audio driver. These components retain their respective
copyrights and license terms.

- VB-CABLE by Vincent Burel / VB-Audio: https://www.vb-cable.com/.
  VB-CABLE is donationware; contributions are welcome. Its unmodified driver
  package and end-user license are included. The project owner confirmed a
  distribution agreement on 2026-10-15. Distribution must remain within that
  agreement's scope; this document does not grant additional vendor rights.
- DPDFNet baseline and DPDFNet2: Daniel Rika, Nino Sapir, Ido Gus / Ceva,
  Apache License 2.0. See `silencio/models/README.md` for sources and hashes.
- GTCRN: Rong Xiaobin, MIT License. See the model attribution above.
- sherpa-onnx / sherpa-onnx-core: k2-fsa, Apache License 2.0.
- ONNX Runtime: Microsoft, MIT License, with upstream third-party notices.
- NumPy and SciPy: BSD licenses, with bundled numerical library notices.
- sounddevice / PortAudio: MIT licenses.
- pystray, keyboard, Pillow, CFFI, pycparser, six, flatbuffers, packaging,
  protobuf, and Python: see their included license texts.
- PyInstaller's bootloader is distributed under its GPL exception for
  applications bundled by PyInstaller. Silencio's source is not relicensed
  by the packaging process.

No audio or microphone recordings are sent to these projects.
