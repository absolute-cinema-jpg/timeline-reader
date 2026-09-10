# PyInstaller spec — builds "Timeline Reader.app" for macOS.
# Build with:  ./build_app.sh   (or:  pyinstaller TimelineReader.spec)

import re
import pathlib

from PyInstaller.utils.hooks import collect_submodules

# Read the real app version from the package so the bundle's Info.plist stays
# in step with timeline_reader/__init__.py (single source of truth).
_init = pathlib.Path("timeline_reader/__init__.py").read_text(encoding="utf-8")
_m = re.search(r'__version__\s*=\s*"([^"]+)"', _init)
VERSION = _m.group(1) if _m else "0.0"

hiddenimports = (
    collect_submodules("aaf2")
    + collect_submodules("avb")
    + collect_submodules("timeline_reader")
    + collect_submodules("openpyxl")   # Excel (.xlsx) export
    + collect_submodules("odf")        # OpenDocument (.ods) export
    + ["et_xmlfile", "defusedxml"]
)

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtCharts", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Timeline Reader",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Timeline Reader",
)
app = BUNDLE(
    coll,
    name="Timeline Reader.app",
    icon="assets/icon.icns",
    bundle_identifier="com.timelinereader.app",
    info_plist={
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Avid / Timeline export",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["public.data"],
                "CFBundleTypeExtensions": ["avb", "edl", "aaf", "txt", "tsv"],
            }
        ],
    },
)
