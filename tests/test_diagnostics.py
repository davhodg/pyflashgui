# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Help > Diagnostics: a window of its own, and what was asked of the probe.

The report went through the Event Log, and said only the versions and the
panes out on their own. It opens in a window now, and says how the
connection was made, what was done to the target in what order, and what
pyOCD said for itself -- which went nowhere before.
"""

import logging

import pytest
from PySide6.QtGui import QGuiApplication
from test_flash_panes import FLASH_AT, connect, hex_file, idle, said
from test_flash_panes import window as window

from pyflashgui.core.events import ERROR
from pyflashgui.core.library_log import LibraryLog, text_of
from pyflashgui.ui import diagnostics as report
from pyflashgui.ui.help_menu import diagnostics


def section_of(text: str, title: str) -> str:
    """The lines of one section, its heading excluded."""
    lines = text.splitlines()
    body = []
    for line in lines[lines.index(title) + 1 :]:
        if not line.startswith("  "):
            break
        body.append(line)
    return "\n".join(body)


def test_the_connection_files_and_operations_are_reported(window, tmp_path):
    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"new!")])
    connect(window)
    window.files_view.program_button.click()
    idle(window)
    text = diagnostics(window)

    connection = section_of(text, "Connection")
    assert "using Simulated" in connection or "using simulated" in connection.lower()
    assert "connected to sim_single through probe SIM0001" in connection
    assert "not busy" in connection
    assert "SIM0001" in section_of(text, "Probes found")
    assert "flash" in section_of(text, "Memory map")
    files = section_of(text, "Files")
    assert "app.hex: file; Intel HEX 08000000, 4 bytes" in files and "ticked" in files
    operations = section_of(text, "Recent operations")
    assert "Connecting to sim_single: done" in operations
    assert "Programming: done" in operations
    assert operations.index("Connecting") < operations.index("Programming"), "in order"


def test_a_failed_operation_says_why(window, monkeypatch):
    from pyflashgui import backends

    backend = backends.get("simulated")

    def refuse(*_args, **_kwargs):
        from pyflashgui.backends.base import BackendError

        raise BackendError("The probe did not answer.")

    monkeypatch.setattr(type(backend), "connect", refuse)
    window.probe_bar.button.click()
    idle(window)
    operations = section_of(diagnostics(window), "Recent operations")
    assert "Connecting to sim_single: failed: The probe did not answer." in operations


def test_recent_problems_are_in_it(app, window):
    window.events.warning("the target did not answer")
    app.processEvents()
    assert "warning: the target did not answer" in diagnostics(window)


def test_a_section_that_fails_costs_only_itself(window, monkeypatch):
    def broken(_window):
        raise RuntimeError("odd state")

    monkeypatch.setattr(report, "SECTIONS", (("Broken", broken), *report.SECTIONS[1:]))
    text = diagnostics(window)
    assert "could not be read: RuntimeError: odd state" in text
    assert section_of(text, "Threads"), "the rest is still there"


def test_every_section_says_something(window):
    text = diagnostics(window)
    for title, _build in report.SECTIONS:
        assert section_of(text, title), f"{title} says something, if only nothing"


def test_it_opens_in_a_window_of_its_own_and_is_copied(app, window, tmp_path, monkeypatch):
    from pyflashgui.ui import folders

    window.help_menu._show_diagnostics()
    dialog = window.help_menu.diagnostics
    assert dialog.isVisible() and "Connection" in dialog.report()
    assert QGuiApplication.clipboard().text() == dialog.report(), "as the bug report form says"
    assert "Recent operations" not in window.log.toPlainText(), "not through the Event Log"

    window.help_menu._show_diagnostics()
    assert window.help_menu.diagnostics is dialog, "one window, brought forward"

    path = tmp_path / "report.txt"
    monkeypatch.setattr(folders, "save_file", lambda *a, **k: str(path))
    dialog.save()
    assert "Connection" in path.read_text(encoding="utf-8")
    dialog.close()


# --- what pyOCD says for itself ----------------------------------------------------------
def test_pyocd_s_errors_reach_the_event_log_and_everything_is_kept(app, window):
    """pyOCD reports some faults only in its own log: a flash routine that ended
    in a HardFault said "IPSR should be 0 but is 0x3" there and nowhere else."""
    log = logging.getLogger("pyocd.flash.flash")
    log.info("Erased 4096 bytes")
    log.warning("an ordinary warning")
    log.error("IPSR should be 0 but is 0x%x", 3)
    app.processEvents()

    assert said(window, ERROR)[-1] == "pyOCD: IPSR should be 0 but is 0x3"
    assert not any("ordinary warning" in line for _level, line in window.said), "kept only"
    kept = section_of(diagnostics(window), "pyOCD and pylink log")
    assert "pyOCD info: Erased 4096 bytes" in kept
    assert "pyOCD warning: an ordinary warning" in kept
    assert "pyOCD error: IPSR should be 0 but is 0x3" in kept


def test_pylink_is_listened_to_as_well(app, window):
    logging.getLogger("pylink.jlink").error("could not open the J-Link")
    app.processEvents()
    assert said(window, ERROR)[-1] == "pylink: could not open the J-Link"


def test_a_closed_window_stops_listening(app, window):
    handler = window.library_log
    window.close()
    assert handler not in logging.getLogger("pyocd").handlers
    # Reopened by the fixture's own close, which is harmless twice.


def test_the_exception_a_line_carries_is_said_once():
    try:
        raise OSError("the probe was unplugged")
    except OSError:
        import sys

        info = sys.exc_info()
    record = logging.LogRecord(
        "pyocd", logging.ERROR, "", 0, "Error during board uninit:", (), info
    )
    assert text_of(record) == "Error during board uninit: the probe was unplugged"
    same = logging.LogRecord("pyocd", logging.ERROR, "", 0, "the probe was unplugged", (), info)
    assert text_of(same) == "the probe was unplugged"


def test_a_handler_whose_window_has_gone_says_nothing_and_raises_nothing():
    class Gone:
        def error(self, _text):
            raise RuntimeError("Internal C++ object already deleted.")

    handler = LibraryLog(Gone())
    handler.emit(logging.LogRecord("pyocd", logging.ERROR, "", 0, "late", (), None))
    assert handler.lines()[-1].endswith("pyOCD error: late")


@pytest.mark.parametrize("name, library", [("pyocd.coresight.ap", "pyOCD"), ("pylink", "pylink")])
def test_each_line_is_named_after_its_library(name, library):
    from pyflashgui.core.library_log import library_of

    assert library_of(name) == library
