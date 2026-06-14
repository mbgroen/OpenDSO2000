# PyInstaller spec — builds the OpenDSO2000 binary for the host platform.
#   macOS   -> OpenDSO2000.app   (windowed .app bundle, icon.icns)
#   Windows -> OpenDSO2000.exe   (one-file, windowed, icon.ico)
#   Linux   -> dist/OpenDSO2000/ (one-dir; wrapped into an AppImage by CI)
#
# Build from the repo root:  pyinstaller packaging/opendso2000.spec
import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # repo root (packaging/..)

# Bundle the app's icon/PNG assets so the running app finds them (app_icon()).
datas = [(os.path.join(ROOT, "opendso2000", "res"), "opendso2000/res")]
binaries = []
hiddenimports = []

# Pull in libusb-package's prebuilt native libusb so USB works in the bundle.
for pkg in ("libusb_package",):
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
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    # One self-contained .exe.
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="OpenDSO2000",
        console=False,
        icon=icon,
        upx=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="OpenDSO2000",
        console=False,
        icon=icon,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="OpenDSO2000", upx=False)
    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="OpenDSO2000.app",
            icon=icon,
            bundle_identifier="io.github.mbgroen.opendso2000",
            info_plist={
                "CFBundleName": "OpenDSO2000",
                "CFBundleDisplayName": "OpenDSO2000",
                "CFBundleShortVersionString": "0.1.0",
                "NSHighResolutionCapable": True,
            },
        )
