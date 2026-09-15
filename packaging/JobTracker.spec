# Only explicit runtime packages and browser binaries are included, never project data.
import json
import os
import sys
from pathlib import Path
import playwright
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")))
if str(cache) == "0":
    cache = Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
metadata = json.loads((Path(playwright.__file__).parent / "driver" / "package" / "browsers.json").read_text())
datas = []
for browser in metadata["browsers"]:
    if browser["name"] in ("chromium", "chromium-headless-shell", "ffmpeg", "winldd"):
        folder = browser["name"].replace("-", "_") + "-" + browser["revision"]
        source = cache / folder
        if not source.is_dir():
            raise RuntimeError(f"Missing browser: {source}. Run: python -m playwright install chromium")
        datas.append((str(source), "browsers/" + folder))
datas += copy_metadata("keyring")
binaries = []
conda_bin = Path(sys.prefix) / "Library" / "bin"
if conda_bin.is_dir():
    os.environ["PATH"] = str(conda_bin) + os.pathsep + os.environ.get("PATH", "")
    for name in ("liblzma.dll", "LIBBZ2.dll", "libexpat.dll", "ffi.dll", "sqlite3.dll"):
        dll = conda_bin / name
        if dll.is_file():
            binaries.append((str(dll), "."))

a = Analysis(
    [str(root / "main.py")], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=["keyring.backends.Windows", "win32ctypes.pywin32.win32cred"],
    hookspath=[], runtime_hooks=[],
    excludes=["pandas", "numpy", "matplotlib", "scipy", "IPython", "PyQt5", "PySide2", "PySide6", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name="JobTracker", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False,
)
