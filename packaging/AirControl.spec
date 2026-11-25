# Windows x64, console, folder distribution. Keep the whole AirControl folder.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
mp_data, mp_binaries, mp_imports = collect_all("mediapipe")
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=mp_binaries,
    datas=mp_data + [
        (str(root / "models" / "hand_landmarker.task"), "models"),
        (str(root / "models" / "README.md"), "models"),
    ],
    hiddenimports=mp_imports + ["mediapipe.tasks.c"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="AirControl", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AirControl")
