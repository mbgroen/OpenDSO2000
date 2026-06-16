# PyInstaller spec — builds the OpenDSO2000 web-server binary for the host.
#   macOS   -> OpenDSO2000.app   (.app bundle, icon.icns)
#   Windows -> OpenDSO2000.exe   (one-file, icon.ico)
#   Linux   -> dist/OpenDSO2000/ (one-dir; wrapped into an AppImage by CI)
#
# Running the binary starts the web server and (when double-clicked) opens the
# browser UI. Build from the repo root:  pyinstaller packaging/opendso2000.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # repo root (packaging/..)

# Bundle icons and the web UI assets so the server can serve them.
datas = [
    (os.path.join(ROOT, "opendso2000", "res"), "opendso2000/res"),
    (os.path.join(ROOT, "opendso2000", "server", "static"), "opendso2000/server/static"),
]
binaries = []
hiddenimports = []

# Collect packages with dynamic imports / native libs that PyInstaller's static
# analysis misses (uvicorn's loop/protocol plugins, the bundled libusb, etc.).
for pkg in ("libusb_package", "uvicorn", "fastapi", "starlette", "anyio",
            "websockets", "h11", "click"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

icon = None
if sys.platform == "darwin":
    icon = os.path.join(ROOT, "opendso2000", "res", "icon.icns")
elif sys.platform == "win32":
    icon = os.path.join(ROOT, "opendso2000", "res", "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "run_opendso2000.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6", "PyQt5", "PyQt6", "pyqtgraph", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="OpenDSO2000", console=False, icon=icon, upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="OpenDSO2000", console=False, icon=icon, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="OpenDSO2000", upx=False)
    if sys.platform == "darwin":
        app = BUNDLE(
            coll, name="OpenDSO2000.app", icon=icon,
            bundle_identifier="io.github.mbgroen.opendso2000",
            info_plist={
                "CFBundleName": "OpenDSO2000",
                "CFBundleDisplayName": "OpenDSO2000",
                "CFBundleShortVersionString": "0.3.1",
                "NSHighResolutionCapable": True,
                "LSBackgroundOnly": False,
            },
        )
