# PyInstaller specification for pyflashgui. Build with: build.cmd
#
# One thing needs care here, because PyInstaller works by *reading the source*
# to find imports and files:
#
# * pyOCD finds its probe drivers and RTOS plugins through entry points at run
#   time, so nothing imports those modules statically and PyInstaller would
#   leave every one of them out -- and with no entry points in the bundle,
#   pyOCD would look for them and find none. So pyOCD is swept whole, and its
#   package metadata, which is where the entry points are written, goes in as
#   data.
#
# Qt is left as separate DLLs (a one-directory build) so it stays dynamically
# linked and replaceable, which is what the LGPL asks for; libusb is the same.
# GPL-only Qt modules are excluded here and the build fails if any of them
# appear anyway.

from pathlib import Path

import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

PROJECT = Path(SPECPATH).parent

# pyOCD whole: its probe drivers, its built-in targets and the data files
# beside them (the SVD archive, the default debug sequences).
PYOCD_DATA, PYOCD_BINARIES, PYOCD_HIDDEN = collect_all("pyocd")
# What pyOCD reaches USB and packs through. Each carries a native library of
# its own beside the Python, which a plain import would not bring.
for _package in ("libusb_package", "cmsis_pack_manager", "capstone"):
    _data, _binaries, _hidden = collect_all(_package)
    PYOCD_DATA += _data
    PYOCD_BINARIES += _binaries
    PYOCD_HIDDEN += _hidden

HIDDEN = [
    *PYOCD_HIDDEN,
    "bincopy",
    # J-Link, through SEGGER's own library, which the user installs. pyOCD
    # imports it only when it looks for a J-Link.
    "pylink",
    "hid",
    "usb.backend.libusb1",
]

# Qt modules that are GPL or commercial only. Shipping one would change the
# licence of the whole application, so they are kept out deliberately.
GPL_QT_MODULES = [
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtWaylandCompositor",
]

EXCLUDED = [
    *GPL_QT_MODULES,
    # Qt modules pyflashgui does not use.
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    # developer tooling that has no business in a release build
    "pytest",
    "ruff",
    "PyInstaller",
]

DATA = [
    # The icon and the manual, read as files at run time.
    (str(PROJECT / "pyflashgui" / "resources"), "pyflashgui/resources"),
    (str(PROJECT / "pyflashgui" / "help"), "pyflashgui/help"),
    (str(PROJECT / "LICENSE"), "."),
    (str(PROJECT / "NOTICE"), "."),
    (str(PROJECT / "THIRD-PARTY-NOTICES.txt"), "."),
    (str(PROJECT / "README.md"), "."),
    *PYOCD_DATA,
    # The packages' own records, which About and the diagnostics report read
    # to list what pyflashgui runs on and which version of each is here.
    # pyflashgui's names what it requires; recursive follows those, and
    # reaches pyOCD's, whose entry points are how it finds a probe driver.
    *copy_metadata("pyflashgui", recursive=True),
]

#: Qt ships these as plain DLLs and plugins collected by PySide6's own
#: PyInstaller hook, so ``excludes`` (which only filters Python modules) does
#: not remove them. They have to be filtered out of the collected binaries.
GPL_QT_BINARY_TOKENS = (
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6virtualkeyboard",
    "qt6waylandcompositor",
    "virtualkeyboardplugin",
)


def _is_gpl_qt(entry) -> bool:
    name = Path(entry[0]).name.lower()
    return any(token in name for token in GPL_QT_BINARY_TOKENS)


analysis = Analysis(
    [str(PROJECT / "pyflashgui" / "__main__.py")],
    pathex=[str(PROJECT)],
    binaries=PYOCD_BINARIES,
    datas=DATA,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED,
    noarchive=False,
)

analysis.binaries = TOC(e for e in analysis.binaries if not _is_gpl_qt(e))
analysis.datas = TOC(e for e in analysis.datas if not _is_gpl_qt(e))

pyz = PYZ(analysis.pure)

# The version resource, which Windows shows under Properties > Details and
# which code signing requires: the product name and version, the same in every
# file of one build. The same version the installer is built as.
sys.path.insert(0, str(PROJECT / "build"))
import version as _version  # noqa: E402

_package = _version.package_version()
_numbers = tuple(int(n) for n in _version.file_version(_package).split("."))
_product_version = _version.installer_version(_package, *_version.this_commit())
VERSION_RESOURCE = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_numbers, prodvers=_numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "davhodg"),
                        StringStruct("FileDescription", "pyflashgui, a flash programming tool"),
                        StringStruct("FileVersion", _product_version),
                        StringStruct("InternalName", "pyflashgui"),
                        StringStruct("LegalCopyright", "Apache License 2.0"),
                        StringStruct("OriginalFilename", "pyflashgui.exe"),
                        StringStruct("ProductName", "pyflashgui"),
                        StringStruct("ProductVersion", _product_version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="pyflashgui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX compression is a reliable way to be flagged by antivirus
    console=False,  # a GUI application: no console window
    # Explorer, the Start menu and the desktop shortcut read the icon out of
    # the exe, not from the running window. Regenerate with build/icon.py.
    icon=str(PROJECT / "pyflashgui" / "resources" / "pyflashgui.ico"),
    version=VERSION_RESOURCE,
)

COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="pyflashgui",
)
