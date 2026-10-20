# Build with: python -m PyInstaller --noconfirm packaging/Silencio.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

root = Path(SPECPATH).parent
datas = collect_data_files("silencio", includes=["models/*"])
datas += [(str(root / "packaging/vendor/vbcable"), "vendor/vbcable"),
          (str(root / "packaging/vendor/vbcable-manifest.json"), "vendor"),
          (str(root / "packaging/assets/silencio.ico"), "assets")]
binaries = collect_dynamic_libs("sherpa_onnx") + collect_dynamic_libs("onnxruntime")
hiddenimports = ["pystray._win32", "keyboard", "PIL.ImageDraw", "tkinter", "tkinter.ttk",
                 "sherpa_onnx.lib._sherpa_onnx", "onnxruntime.capi.onnxruntime_pybind11_state"]
a = Analysis([str(root / "packaging/entry.py")], pathex=[str(root / "src")],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    excludes=["torch", "tensorflow", "matplotlib", "pandas", "PySide6", "IPython", "pytest", "numba",
              "onnxruntime.tools", "onnxruntime.transformers", "onnxruntime.quantization", "onnxruntime.training"],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Silencio", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon=str(root / "packaging/assets/silencio.ico"),
    version=str(root / "packaging/version.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Silencio")
