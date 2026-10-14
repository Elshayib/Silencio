# Bundled local models

No model is downloaded at runtime. SHA-256 is verified before audio starts.

`dpdfnet_baseline.onnx`: DPDFNet baseline 16 kHz streaming export, Apache 2.0.
Same source project, authors and license as DPDFNet2 below.
Export: https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/dpdfnet_baseline.onnx
SHA-256: `debaf0e8893479fca91b8b4c1eae8db195aa8980ccc9012f5809fde2b738151a`.
Unmodified model. Selected for the laptop default because it keeps greater
CPU headroom than DPDFNet2 with a small loss on the paired-mixture test.

`dpdfnet2.onnx`: DPDFNet2 16 kHz streaming export, Apache 2.0.
Authors: Daniel Rika, Nino Sapir, Ido Gus / Ceva.
Source project: https://github.com/ceva-ip/DPDFNet
Source reference: `9bd9844a227bb6aa57e55588d8d0e961fcff1c46`.
Export: https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/dpdfnet2.onnx
SHA-256: `ce35d6025fc71df0ef10d1540e1b7916837bbfe5f6896deb744508d2cad487a9`.
Unmodified model, bundled with `DPDFNET-LICENSE.txt`. Used with sherpa-onnx
1.13.8's streaming implementation. Its four internal delay hops are included
in Silencio's reported latency.

`gtcrn.onnx`: GTCRN DNS3 streaming `gtcrn_simple.onnx` export, MIT.
Copyright (c) 2024 Rong Xiaobin.
Source: https://github.com/Xiaobin-Rong/gtcrn/blob/502ebfab64da7c4a9af78dcb9c6ceef1ebb01c73/stream/onnx_models/gtcrn_simple.onnx
SHA-256: `b4718df6228e7bdf1a8a435cf98f838636eb2fd331acabf86ba87c5192ebcb87`.
Unmodified model, bundled with `GTCRN-LICENSE.txt`.

These are speech enhancement models. Music overlapping speech can remain;
singing, distant/quiet Vocal and SFX can be suppressed. They are not perfect
music-stem separators. Silencio's fast residual postfilter is external to
GTCRN and is not a claimed upstream capability.
