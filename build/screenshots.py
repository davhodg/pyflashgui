# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Regenerate the screenshot the README and the manual share: the main window
on the simulated probe.

    python build/screenshots.py [out.png]

It opens pyflashgui in its default layout, connects the simulated probe to
its simulated target, programs a small made-up firmware file and reads the
start of the flash back, then saves the window. The window is on screen for a
few seconds while it does; leave it be.

A throwaway PYFLASHGUI_HOME and QSettings file are used, so your own
workspace, layout and remembered answers are neither read nor written. Only
the simulated probe and a file made here are involved, so nothing that is not
pyflashgui's own can end up in the picture.
"""

from __future__ import annotations

import os
import random
import struct
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
#: Beside the manual's pages, because the manual shows it too and a picture has
#: to be package data to be in a wheel or an installer.
DEFAULT_OUT = PROJECT / "pyflashgui" / "help" / "main-window.png"
SIZE = (1400, 900)
FLASH = 0x0800_0000
#: How much of the flash is read back for the picture.
READ = 0x1000


def firmware() -> bytes:
    """Bytes that look like firmware: a vector table, some text, and code.

    Made the same way every time, so that the picture changes only when
    pyflashgui does.
    """
    made = random.Random(2026)
    vectors = struct.pack("<I", 0x2000_4000) + b"".join(
        struct.pack("<I", FLASH + 0x200 + 2 * made.randrange(0, 0x1800) + 1) for _ in range(15)
    )
    text = b"pyflashgui demo firmware 0.1.0\x00built for sim_single\x00\x00"
    code = bytes(made.randrange(256) for _ in range(0x2C00))
    return vectors + text + code


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    home = tempfile.mkdtemp(prefix="pyflashgui-screenshot-")
    os.environ["PYFLASHGUI_HOME"] = home

    import bincopy
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path(home) / "qsettings"))
    app = QApplication(sys.argv)

    from pyflashgui.__main__ import set_icon
    from pyflashgui.core import workspaces
    from pyflashgui.core.settings import Settings
    from pyflashgui.ui import probe_bar
    from pyflashgui.ui.main_window import MainWindow

    set_icon(app)
    settings = Settings(workspaces.settings_path())
    settings.set(probe_bar.BACKEND_KEY, "simulated")
    settings.set(probe_bar.TARGET_KEY, "sim_single")

    made = bincopy.BinFile()
    made.add_binary(firmware(), address=FLASH)
    file = Path(home) / "app.hex"
    file.write_text(made.as_ihex())

    window = MainWindow()
    window.resize(*SIZE)
    window.move(40, 40)
    window.show()

    def pump(seconds: float, until=None) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.01)
        return until() if until is not None else True

    def idle() -> bool:
        return pump(20, lambda: not window.flasher.busy) and pump(0.3)

    flasher, files = window.flasher, window.files_view
    if not pump(20, lambda: window.probe_bar.chosen_probe() and flasher.regions):
        print("the simulated probe never appeared", file=sys.stderr)
        return 1
    window.probe_bar.button.click()
    if not pump(20, lambda: flasher.connected):
        print("the simulated probe did not connect", file=sys.stderr)
        return 1
    files.add_files([str(file)])
    files.program_button.click()
    idle()
    flasher.read_memory(FLASH, READ)
    idle()
    if len(files.entries) != 2:
        print("the read never arrived", file=sys.stderr)
        return 1
    # Room for the bytes and their text: the list beside them needs less.
    docks = window.panes.docks
    window.resizeDocks([docks["files"], docks["memory 2"]], [45, 55], Qt.Horizontal)
    pump(1)

    out.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(out)):
        print(f"could not write {out}", file=sys.stderr)
        return 1
    print(f"saved {out} ({window.width()}x{window.height()})")
    # Nothing to ask about on the way out: the read was made for the picture.
    for entry in files.entries:
        entry.unsaved = False
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
