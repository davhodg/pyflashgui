# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Python Console, and ``flash``, on the simulated probe."""

import time

import bincopy
import pytest
from PySide6.QtCore import QCoreApplication, QSettings, QTimer

from pyflashgui import backends
from pyflashgui.ui import probe_bar
from pyflashgui.ui.console_view import ConsoleView
from pyflashgui.ui.scripting import ScriptError, ScriptStoppedError

PROBE = "SIM0001"
FLASH_AT = 0x0800_0000
RAM_AT = 0x2000_0000


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def hex_file(folder, name: str, address: int, data: bytes) -> str:
    made = bincopy.BinFile()
    made.add_binary(data, address=address)
    path = folder / name
    path.write_text(made.as_ihex())
    return str(path)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from pyflashgui.core import workspaces
    from pyflashgui.core.settings import Settings
    from pyflashgui.ui.main_window import MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()
    settings = Settings(workspaces.settings_path())
    settings.set(probe_bar.BACKEND_KEY, "simulated")
    settings.set(probe_bar.TARGET_KEY, "sim_single")
    made = MainWindow()
    made.said = []
    made.events.posted.connect(lambda message, level: made.said.append((level, message)))
    made.show()
    wait_for(lambda: made.probe_bar.chosen_probe() == PROBE and made.flasher.regions)
    yield made
    wait_for(lambda: not made.flasher.busy)
    for entry in made.files_view.entries:
        entry.unsaved = False
    made.close()


@pytest.fixture
def flash(window):
    return window.flash


@pytest.fixture
def console(window) -> ConsoleView:
    view = window.panes.view("console")
    view.output.clear()
    return view


def typed(console: ConsoleView, *lines: str) -> str:
    """What the console shows after these lines are typed into it."""
    console.output.clear()
    for line in lines:
        console.input.setText(line)
        console.input.returnPressed.emit()
    return console.output.toPlainText()


def board():
    return backends.get("simulated").board(PROBE)


# --- flash ----------------------------------------------------------------------------
def test_each_call_waits_for_its_answer(flash, tmp_path):
    assert repr(flash) == "<flash: not connected>"
    flash.connect()
    assert flash.connected and flash.target == "sim_single" and flash.probe == PROBE
    assert repr(flash) == f"<flash: sim_single through probe {PROBE}>"
    flash.connect()  # what is connected already is left as it is

    flash.program(hex_file(tmp_path, "app.hex", FLASH_AT, b"hello"))
    assert flash.read(FLASH_AT, 5) == b"hello"
    assert board().resets == 1, "restarted, as Program and verify does"
    assert flash.verify(hex_file(tmp_path, "other.hex", FLASH_AT, b"HELLO")) is False
    assert flash.verify(str(tmp_path / "app.hex")) is True

    flash.erase(FLASH_AT, 0x1000)
    assert flash.read(FLASH_AT, 5) == b"\xff" * 5
    flash.program(str(tmp_path / "app.hex"), verify=False)
    flash.erase()
    assert flash.read(FLASH_AT, 5) == b"\xff" * 5

    flash.write(RAM_AT, b"\x01\x02")
    assert flash.read(RAM_AT, 2) == b"\x01\x02"
    flash.reset(halt=True)
    assert board().resets == 3

    flash.disconnect()
    assert not flash.connected


def test_a_read_by_a_script_is_not_listed_unless_asked(window, flash):
    flash.connect()
    flash.read(FLASH_AT, 16)
    assert window.files_view.entries == []
    flash.read(FLASH_AT, 16, show=True)
    assert [e.name for e in window.files_view.entries] == ["Read 1"]
    assert window.files_view.entries[0].target == "sim_single"


def test_what_is_ticked_is_programmed_when_nothing_is_named(window, flash, tmp_path):
    flash.connect()
    with pytest.raises(ScriptError, match="Nothing is ticked"):
        flash.program()
    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT + 0x100, b"ticked")])
    flash.program()
    assert flash.read(FLASH_AT + 0x100, 6) == b"ticked"
    assert flash.verify() is True


def test_what_was_not_done_is_raised_with_the_event_logs_words(flash, tmp_path):
    with pytest.raises(ScriptError, match="needs a probe connected"):
        flash.read(FLASH_AT, 4)
    flash.connect()
    with pytest.raises(
        ScriptError, match=r"Not written: 08000000 is flash \(flash\), and flash is programmed"
    ):
        flash.write(FLASH_AT, b"\x00")
    with pytest.raises(ScriptError, match="Not programmed: "):
        flash.program(hex_file(tmp_path, "far.hex", 0x3000_0000, b"nowhere"))
    with pytest.raises(ScriptError, match="cannot be read"):
        flash.program(str(tmp_path / "missing.hex"))
    with pytest.raises(ScriptError, match="give both an address and a length"):
        flash.erase(FLASH_AT)
    with pytest.raises(ScriptError, match="The target has no memory at 30000000"):
        flash.read(0x3000_0000, 4)
    with pytest.raises(ScriptError, match="Disconnect first"):
        flash.connect(target="sim_dual")


def test_a_raw_binary_is_given_its_address(flash, tmp_path):
    raw = tmp_path / "app.bin"
    raw.write_bytes(b"raw!")
    flash.connect()
    flash.program(str(raw), address=FLASH_AT + 0x2000)
    assert flash.read(FLASH_AT + 0x2000, 4) == b"raw!"


def test_a_question_answered_no_stops_the_script(window, flash, tmp_path, monkeypatch):
    flash.connect()
    monkeypatch.setattr(window.files_view, "may_erase", lambda _ranges: False)
    with pytest.raises(ScriptError, match="answered No"):
        flash.erase()


# --- the console ----------------------------------------------------------------------
def test_the_console_has_flash_and_shows_what_is_printed(window, console):
    shown = typed(console, "flash.connect()", "print(flash.read(0x08000000, 4).hex())")
    assert "ffffffff" in shown
    assert window.flasher.connected


def test_a_script_error_is_a_sentence_and_a_mistake_is_a_traceback(console):
    shown = typed(console, "flash.read(0, 4)")
    assert "ScriptError: Reading needs a probe connected to a target first." in shown
    assert "Traceback" not in shown
    shown = typed(console, "no_such_name")
    assert "Traceback" in shown and "NameError" in shown


def test_a_block_over_several_lines_is_run_when_it_ends(console):
    console.input.setText("for n in range(2):")
    console.input.returnPressed.emit()
    assert console.prompt.text() == "..."
    shown = typed(console, "    print('line', n)", "")
    assert "line 0" in shown and "line 1" in shown
    assert console.prompt.text() == ">>>"


def test_a_script_runs_with_the_same_names_and_prints_as_it_goes(window, console, tmp_path):
    script = tmp_path / "check.py"
    script.write_text(
        "flash.connect()\n"
        "flash.write(0x20000000, b'abc')\n"
        "print('read', flash.read(0x20000000, 3))\n"
        "log('from the script')\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    console.run_file(str(script))
    shown = console.output.toPlainText()
    assert f"--- running {script}" in shown
    assert "read b'abc'" in shown
    assert "the script called exit" in shown
    assert f"--- {script} has finished" in shown
    assert "from the script" in [message for _level, message in window.said]


def test_stop_ends_a_script_at_its_next_wait(console):
    QTimer.singleShot(100, console.stop)
    started = time.monotonic()
    console.run_source("while True:\n    wait(0.05)\n", "forever.py")
    assert time.monotonic() - started < 3
    assert "Stopped." in console.output.toPlainText()
    assert not console.running and console.input.isEnabled()


def test_a_stopped_flash_call_raises_stopped(flash):
    flash.stop()
    with pytest.raises(ScriptStoppedError):
        flash.wait(0)
    flash.started()
    flash.wait(0)


def test_the_window_does_not_close_while_a_script_runs(window, console):
    console.run_source("window.close()\nprint('still open:', window.isVisible())\n")
    assert "still open: True" in console.output.toPlainText()
    assert any("A script is running" in message for _level, message in window.said)


def test_the_console_is_in_the_view_menu_and_opens_in_front(window):
    entries = {a.text(): a for a in window.view_menu.actions()}
    assert "Python Console" in entries
    dock = window.panes.docks["console"]
    assert dock.isHidden(), "it starts hidden"
    entries["Python Console"].trigger()
    assert not dock.isHidden() and dock.isFloating(), "and the first time, in front"

    window.reset_layout_action.trigger()
    assert dock.isHidden() and not dock.isFloating()
    window._build_view_menu()
    {a.text(): a for a in window.view_menu.actions()}["Python Console"].trigger()
    assert dock.isFloating(), "in front again, as at first"
