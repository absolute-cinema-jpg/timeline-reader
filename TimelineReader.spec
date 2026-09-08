# PyInstaller spec — builds "Timeline Reader.app" for macOS.
# Build with:  ./build_app.sh   (or:  pyinstaller TimelineReader.spec)

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("aaf2")
    + collect_submodules("avb")
    + collect_submodules("timeline_reader")
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
        "CFBundleShortVersionString": "0.1.0",
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
