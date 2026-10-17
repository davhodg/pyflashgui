# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The probe bar and the Files pane with its memory map, on the simulated probe."""

import time

import bincopy
import pytest
from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtWidgets import QMessageBox

from pyflashgui import backends
from pyflashgui.core.events import ERROR, GOOD, INFORMATION, WARNING
from pyflashgui.ui import files_view, probe_bar
from pyflashgui.ui.files_view import ADDRESS, END, FILE, FORMAT, SIZE, parse_address

PROBE = "SIM0001"
FLASH_AT = 0x0800_0000


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
    """A window in a workspace of its own, already set to the simulated probe."""
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
    # The bar asks for the probes and the targets once the window is up.
    wait_for(lambda: made.probe_bar.chosen_probe() == PROBE and made.flasher.regions)
    yield made
    wait_for(lambda: not made.flasher.busy)
    for entry in made.files_view.entries:
        entry.unsaved = False
    made.close()


def said(window, level: str) -> list[str]:
    return [message for at, message in window.said if at == level]


def connect(window) -> None:
    window.probe_bar.button.click()
    wait_for(lambda: window.flasher.connected)


def idle(window) -> None:
    wait_for(lambda: not window.flasher.busy)
    QCoreApplication.processEvents()


# --- the bar --------------------------------------------------------------------------
def test_the_bar_lists_what_the_backend_has_and_what_was_chosen_last(window):
    bar = window.probe_bar
    assert bar.backend.currentData() == "simulated"
    assert [bar.probe.itemData(i) for i in range(bar.probe.count())] == ["SIM0001", "SIM0002"]
    assert bar.target.findText("sim_dual") >= 0
    assert bar.chosen_target() == "sim_single"
    assert bar.button.isEnabled() and bar.button.text() == "Connect"


def test_connect_becomes_disconnect_and_the_choices_are_held(window):
    bar = window.probe_bar
    connect(window)
    assert bar.button.text() == "Disconnect" and bar.button.isChecked()
    assert not bar.target.isEnabled() and not bar.probe.isEnabled()
    bar.button.click()
    assert not window.flasher.connected
    assert bar.button.text() == "Connect" and bar.target.isEnabled()


def test_a_connect_that_fails_puts_the_button_back(window, monkeypatch):
    backend = backends.get("simulated")
    monkeypatch.setattr(
        type(backend), "connect", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no power"))
    )
    window.probe_bar.button.click()
    wait_for(lambda: not window.flasher.busy and said(window, ERROR))
    QCoreApplication.processEvents()
    assert not window.probe_bar.button.isChecked()
    assert window.probe_bar.button.text() == "Connect"


def test_what_is_chosen_is_kept_in_the_workspace(window):
    bar = window.probe_bar
    bar.probe.setCurrentIndex(1)
    bar.target.setEditText("sim_dual")
    bar.frequency.setCurrentIndex(bar.frequency.findData(1_000_000))
    settings = window.ctx.settings
    assert settings.get(probe_bar.PROBE_KEY) == "SIM0002"
    assert settings.get(probe_bar.TARGET_KEY) == "sim_dual"
    assert settings.get(probe_bar.FREQUENCY_KEY) == 1_000_000


def test_with_no_probe_there_is_nothing_to_connect_to(window):
    window.probe_bar._show_probes([])
    assert window.probe_bar.probe.currentText() == probe_bar.NO_PROBES
    assert not window.probe_bar.button.isEnabled()


# --- the list of files ----------------------------------------------------------------
def test_a_file_added_is_read_listed_and_kept(window, tmp_path):
    files = window.files_view
    path = hex_file(tmp_path, "app.hex", FLASH_AT, bytes(1536))
    files.add_files([path, path])  # the same one twice is one
    assert files.table.rowCount() == 1
    cells = [files.table.item(0, c).text() for c in (FILE, FORMAT, ADDRESS, SIZE)]
    assert cells == ["app.hex", "Intel HEX", "08000000", "1.5 KiB"]
    assert files.table.item(0, FILE).checkState() == Qt.Checked
    assert window.ctx.settings.get(files_view.FILES_KEY) == [
        {"path": path, "address": None, "enabled": True}
    ]


def test_a_raw_binary_waits_for_its_address(window, tmp_path):
    files = window.files_view
    path = tmp_path / "app.bin"
    path.write_bytes(bytes(64))
    files.add_files([str(path)])
    assert files.table.item(0, FORMAT).text() == "Cannot be read"
    assert "start address" in files.table.item(0, FORMAT).toolTip()
    assert files.loaded() == []
    assert files.table.item(0, ADDRESS).flags() & Qt.ItemIsEditable

    files.table.item(0, ADDRESS).setText("0x0800_1000")
    assert files.table.item(0, FORMAT).text() == "raw binary"
    assert files.table.item(0, ADDRESS).text() == "08001000"
    assert files.loaded()[0].address == 0x0800_1000


def test_an_address_that_is_not_one_is_said_and_not_taken(window, tmp_path):
    files = window.files_view
    path = tmp_path / "app.bin"
    path.write_bytes(bytes(64))
    files.add_files([str(path)])
    files.table.item(0, ADDRESS).setText("somewhere")
    assert "is not an address" in said(window, WARNING)[-1]
    assert files.table.item(0, ADDRESS).text() == ""


def test_addresses_are_taken_as_they_are_typed():
    assert parse_address("08000000") == 0x0800_0000
    assert parse_address(" 0x1000_0000 ") == 0x1000_0000
    assert parse_address("1 0000") == 0x1_0000
    assert parse_address("") is None and parse_address("xyz") is None
    assert parse_address("1FFFFFFFF") is None, "past the end of a 32-bit address space"


def test_unticking_a_file_takes_it_out_of_what_is_programmed(window, tmp_path):
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))])
    files.table.item(0, FILE).setCheckState(Qt.Unchecked)
    assert files.loaded() == []
    assert window.ctx.settings.get(files_view.FILES_KEY)[0]["enabled"] is False


def test_removing_takes_it_off_the_list_and_leaves_the_file(window, tmp_path):
    files = window.files_view
    path = hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))
    files.add_files([path])
    files.table.selectRow(0)
    files.remove_button.click()
    assert files.table.rowCount() == 0
    assert (tmp_path / "app.hex").exists()


def test_the_list_comes_back_with_the_workspace(window, tmp_path):
    from pyflashgui.ui.files_view import FilesView

    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))])
    again = FilesView(window.flasher, window.ctx, window.confirm)
    assert again.table.item(0, FILE).text() == "app.hex"
    assert again.loaded()[0].size == 16


def test_a_file_rebuilt_on_disc_is_read_again(window, tmp_path):
    files = window.files_view
    path = hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))
    files.add_files([path])
    hex_file(tmp_path, "app.hex", FLASH_AT, bytes(4096))
    wait_for(lambda: files.table.item(0, SIZE).text() == "4.0 KiB")


# --- the buttons ----------------------------------------------------------------------
def test_the_buttons_wait_for_a_connection_and_a_ticked_file(window, tmp_path):
    files = window.files_view
    assert not files.program_button.isEnabled() and not files.erase_button.isEnabled()
    connect(window)
    assert files.erase_button.isEnabled() and files.reset_button.isEnabled()
    assert not files.program_button.isEnabled(), "there is nothing to program yet"
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))])
    assert files.program_button.isEnabled()


def test_program_sends_what_the_file_holds_now(window, tmp_path):
    """Not what it held when it was added: that would be yesterday's firmware."""
    files = window.files_view
    path = hex_file(tmp_path, "app.hex", FLASH_AT, b"old!")
    files.add_files([path])
    connect(window)
    hex_file(tmp_path, "app.hex", FLASH_AT, b"new!")
    files.program_button.click()
    idle(window)
    flash = backends.get("simulated").board(PROBE).memory["flash"]
    assert bytes(flash[:4]) == b"new!"
    assert said(window, GOOD)[-1].startswith("Programmed 1 file, 4 bytes, verified, in ")


def test_program_refuses_what_the_memory_map_calls_an_error(window, tmp_path):
    files = window.files_view
    files.add_files([hex_file(tmp_path, "wrong.hex", 0x4000_0000, bytes(16))])
    connect(window)
    files.program_button.click()
    assert not window.flasher.busy
    errors = said(window, ERROR)
    assert "outside the target's memory" in errors[-2]
    assert errors[-1] == "Not programmed: the Memory Map says what is wrong."


def test_the_button_verifies_and_program_alone_is_under_its_arrow(window, tmp_path):
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"abcd")])
    assert files.program_button.text() == "Program and verify"
    assert [a.text() for a in files.program_button.menu().actions()] == [
        "Program",
        "Program without erasing",
        "Verify",
    ]
    connect(window)

    files.program_only.trigger()
    idle(window)
    assert said(window, GOOD)[-1].startswith("Programmed 1 file, 4 bytes, in ")
    assert backends.get("simulated").board(PROBE).resets == 0, "left stopped: Reset starts it"

    files.program_button.click()
    idle(window)
    assert said(window, GOOD)[-1].startswith("Programmed 1 file, 4 bytes, verified, in ")
    assert backends.get("simulated").board(PROBE).resets == 0


def test_programming_flash_erased_already_leaves_erasing_out(window, tmp_path, monkeypatch):
    """Asked for after a test on an XMC4500: Erase..., then Program erased it
    all over again."""
    from pyflashgui.ui.erase_dialog import EraseDialog

    monkeypatch.setattr(EraseDialog, "exec", lambda dialog: EraseDialog.Accepted)
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"\x0f\x0f\x0f\x0f")])
    connect(window)
    files.erase_button.click()
    idle(window)
    files.program_unerased.trigger()
    idle(window)
    assert said(window, GOOD)[-1].startswith("Programmed 1 file, 4 bytes, without erasing, in ")
    board = backends.get("simulated").board(PROBE)
    assert bytes(board.memory["flash"][:4]) == b"\x0f" * 4

    # Over flash that is not blank, it holds neither, as real flash would;
    # and Verify says so.
    files.add_files([hex_file(tmp_path, "other.hex", FLASH_AT, b"\xf0\xf0\xf0\xf0")])
    files.entries[0].enabled = False
    files.program_unerased.trigger()
    idle(window)
    assert bytes(board.memory["flash"][:4]) == b"\x00" * 4
    files.verify_only.trigger()
    idle(window)
    assert "4 bytes differ of 4" in said(window, ERROR)[-1]


def test_program_without_erasing_is_offered_only_where_it_can_be_done(window):
    files = window.files_view
    assert files.program_unerased.isVisible(), "simulated, as pyOCD, can"
    assert backends.get("pyocd").can_skip_erase
    window.flasher.set_backend("jlink")
    idle(window)
    assert not files.program_unerased.isVisible(), "J-Link Commander erases by itself"


def test_reset_remembers_the_way_chosen_for_the_target(window):
    """Reported on an XMC4500: reset the usual way through pyOCD it stayed
    stopped, and started from its reset pin."""
    files = window.files_view
    connect(window)
    board = backends.get("simulated").board(PROBE)
    assert files.reset_kind() == "default"
    assert [a.text() for a in files.reset_button.menu().actions() if a.isVisible()][-4:] == [
        "Reset the usual way",
        "Reset by the reset pin",
        "Reset by software",
        "Restart the processor only",
    ]
    files.reset_ways["pin"].trigger()
    idle(window)
    assert said(window, INFORMATION)[-1] == "Reset sim_single by its reset pin."
    files.reset_button.click()
    idle(window)
    assert board.reset_kinds[-2:] == ["pin", "pin"], "pressed, the way chosen last"
    assert files.reset_ways["pin"].isChecked()
    assert "by the reset pin" in files.reset_button.toolTip()


def test_a_backend_with_one_way_of_resetting_offers_only_that(window):
    files = window.files_view
    window.flasher.set_backend("jlink")
    idle(window)
    shown = [k for k, a in files.reset_ways.items() if a.isVisible()]
    assert shown == ["default"]
    assert files.reset_kind() == "default"


def test_there_are_no_ticks_beside_the_list(window):
    """What Program does is said on the button that does it."""
    from PySide6.QtWidgets import QCheckBox

    assert window.files_view.findChildren(QCheckBox) == []


def test_verify_erase_and_reset_from_their_buttons(window, tmp_path, monkeypatch):
    from pyflashgui.ui.erase_dialog import EraseDialog

    # The dialog opens on all of the flash, and is agreed to as it opens.
    monkeypatch.setattr(EraseDialog, "exec", lambda dialog: EraseDialog.Accepted)
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"abcd")])
    connect(window)
    files.program_button.click()
    idle(window)
    files.verify_only.trigger()
    idle(window)
    assert said(window, GOOD)[-1] == "Verified: 4 bytes match the files."
    files.erase_button.click()
    idle(window)
    board = backends.get("simulated").board(PROBE)
    assert bytes(board.memory["flash"][:4]) == b"\xff" * 4
    files.verify_only.trigger()
    idle(window)
    assert "4 bytes differ of 4" in said(window, ERROR)[-1]
    files.reset_button.click()
    idle(window)
    assert board.resets == 1, "by Reset alone"


def test_a_real_target_is_asked_about_before_it_is_changed(window, tmp_path, monkeypatch):
    """The simulated one is not: nothing real is on the end of it."""
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"abcd")])
    connect(window)
    asked = []

    def answer(box):
        asked.append(box.text())
        return QMessageBox.Cancel

    from pyflashgui.ui.erase_dialog import EraseDialog

    monkeypatch.setattr(EraseDialog, "exec", lambda dialog: EraseDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "exec", answer)
    monkeypatch.setattr(type(window.flasher.backend), "name", "pyocd")
    files.program_button.click()
    files.erase_button.click()
    assert asked == ["Program sim_single?", "Erase all of the flash of sim_single?"]
    assert not window.flasher.busy, "and Cancel means nothing is done"
    flash = backends.get("simulated").board(PROBE).memory["flash"]
    assert bytes(flash[:4]) == b"\xff" * 4


def test_the_window_does_not_close_part_way_through_a_target(window, tmp_path):
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(8192))])
    connect(window)
    files.program_button.click()
    assert window.flasher.busy
    assert window.close() is False
    assert "still working on the target" in said(window, WARNING)[-1]
    idle(window)


# --- files and reads alike ------------------------------------------------------------
def test_a_file_is_shown_in_a_memory_pane_like_a_read(window, tmp_path):
    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(range(48)))])
    assert window.panes.instances("memory") == ["memory"]
    dock = window.panes.docks["memory"]
    assert dock.windowTitle() == "app.hex" and not dock.isFloating()
    view = window.memory_view
    assert view.summary.text() == "app.hex: Intel HEX, 48 bytes from 08000000 to 0800002F."
    assert view.model.row(1)[0] == "08000010" and view.model.row(1)[1].startswith("10 11 12")
    assert not view.unsaved, "it is on disc already"
    cells = [window.files_view.table.item(0, c).text() for c in (FILE, FORMAT, ADDRESS, END, SIZE)]
    assert cells == ["app.hex", "Intel HEX", "08000000", "0800002F", "48 bytes"]


def test_the_pane_of_a_file_follows_the_file(window, tmp_path):
    path = hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))
    window.files_view.add_files([path])
    hex_file(tmp_path, "app.hex", FLASH_AT, bytes(range(32)))
    wait_for(lambda: len(window.memory_view.model.data_read) == 32, timeout=10.0)
    assert window.memory_view.model.row(1)[1].startswith("10 11")


def test_removing_a_file_closes_its_pane(window, tmp_path):
    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))])
    window.files_view.table.selectRow(0)
    window.files_view.remove_button.click()
    assert window.memory_views == []


def test_the_files_of_a_workspace_have_their_panes_when_it_opens(window, tmp_path):
    from pyflashgui.ui.main_window import MainWindow

    window.files_view.add_files(
        [
            hex_file(tmp_path, "boot.hex", FLASH_AT, bytes(16)),
            hex_file(tmp_path, "app.hex", FLASH_AT + 0x1000, bytes(16)),
        ]
    )
    again = MainWindow()
    try:
        titles = [again.panes.docks[n].windowTitle() for n in again.panes.instances("memory")]
        assert titles == ["boot.hex", "app.hex"]
    finally:
        again.close()


def test_a_ticked_read_is_written_like_a_file(window, tmp_path):
    connect(window)
    window._show_memory(FLASH_AT + 0x2000, b"from a read", "sim_single")
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"from a file")])
    assert [image.name for image in files.loaded()] == ["app.hex"], "a read starts unticked"
    files.table.item(0, FILE).setCheckState(Qt.Checked)
    assert window.map_view.summary.text() == "sim_single: Everything fits."
    assert {window.map_view.pieces.item(r, 0).text() for r in range(2)} == {"Read 1", "app.hex"}
    files.program_button.click()
    idle(window)
    assert said(window, ERROR) == []
    for address in (FLASH_AT, FLASH_AT + 0x2000):
        window.flasher.read_memory(address, 11)
        idle(window)
    assert [e.image.segments[0].data for e in files.entries[-2:]] == [
        b"from a file",
        b"from a read",
    ]


def test_a_read_and_a_file_for_the_same_addresses_are_not_both_written(window, tmp_path):
    connect(window)
    window._show_memory(FLASH_AT, bytes(64), "sim_single")
    files = window.files_view
    files.add_files([hex_file(tmp_path, "app.hex", FLASH_AT + 0x20, bytes(64))])
    files.table.item(0, FILE).setCheckState(Qt.Checked)
    assert "1 error" in window.map_view.summary.text()
    files.program_button.click()
    idle(window)
    assert said(window, ERROR)[-1] == "Not programmed: the Memory Map says what is wrong."


# --- the memory map -------------------------------------------------------------------
def test_the_map_follows_the_files_and_the_target(window, tmp_path):
    view = window.map_view
    assert view.summary.text() == "No file is ticked, so there is nothing to place."
    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(0x1800))])
    assert view.summary.text() == "sim_single: Everything fits."
    assert view.problem_labels == []
    row = [view.pieces.item(0, c).text() for c in range(view.pieces.columnCount())]
    assert row == ["app.hex", "08000000", "080017FF", "6.0 KiB", "flash"]
    figures = view.usage.itemAtPosition(0, 2).widget().text()
    assert figures == "6.0 KiB of 256.0 KiB (2.3 %), erasing 2 sectors, 8.0 KiB"


def test_what_is_wrong_is_said_in_words_at_the_top(window, tmp_path):
    view = window.map_view
    window.files_view.add_files(
        [
            hex_file(tmp_path, "wrong.hex", 0x4000_0000, bytes(16)),
            hex_file(tmp_path, "ram.hex", 0x2000_0000, bytes(16)),
        ]
    )
    assert view.summary.text() == (
        "sim_single: 1 error and 1 warning. These files cannot be programmed as they are."
    )
    lines = [label.text() for label in view.problem_labels]
    assert lines[0].startswith("Error: wrong.hex: 16 bytes at 40000000")
    assert lines[1].startswith("Warning: ram.hex: 16 bytes at 20000000")
    wrong = next(r for r in range(2) if view.pieces.item(r, 0).text() == "wrong.hex")
    assert view.pieces.item(wrong, 4).text() == "Outside the target's memory"


def test_another_target_is_another_map(window, tmp_path):
    view = window.map_view
    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))])
    assert view.summary.text() == "sim_single: Everything fits."
    window.probe_bar.target.setEditText("sim_dual")
    wait_for(lambda: view.summary.text().startswith("sim_dual: 1 error"))


def test_a_target_whose_memory_is_not_known_says_nothing_was_checked(window, tmp_path):
    from pyflashgui.ui import map_view

    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, bytes(16))])
    window.map_view.show_layout(window.files_view.loaded(), [], "some_pack_part")
    assert window.map_view.summary.text() == map_view.UNCHECKED
    assert window.map_view.pieces.item(0, 4).text() == ""


# --- the window -----------------------------------------------------------------------
def test_the_window_opens_with_its_two_panes_and_the_bar(window):
    docks = window.panes.docks
    assert [d.windowTitle() for d in docks.values()] == ["Files", "Event Log", "Python Console"]
    assert window.map_view.isVisible(), "the map is part of the Files pane"
    assert [n for n, dock in docks.items() if dock.isVisible()] == ["files", "log"]
    assert window.probe_bar.isVisible()


def test_the_reset_menu_forgets_folders_and_confirmations(window, tmp_path):
    from pyflashgui.ui import folders

    folders.remember(window.ctx, folders.IMAGE, tmp_path / "app.hex")
    window.confirm.allow("program:rp2350")
    actions = {a.text(): a for a in window.reset_menu.actions()}
    actions["Forget remembered folders"].trigger()
    actions["Re-enable all confirmations"].trigger()
    assert folders.remembered(window.ctx, folders.IMAGE) is None
    assert not window.confirm.agreed("program:rp2350")


def test_the_place_for_memory_is_kept_while_no_memory_pane_is_in_it(window, tmp_path):
    space = window.memory_space
    files_dock = window.panes.docks["files"]
    assert space.isVisible() and "Double-click a file" in space.widget().text()
    assert files_dock.width() < window.width() * 0.7, "the Files pane does not take the width"

    window.files_view.add_files([hex_file(tmp_path, "app.hex", FLASH_AT, b"abcd")])
    entry = window.files_view.entries[0]
    window._open_memory(entry)
    wait_for(lambda: not space.isVisible())
    (name,) = window.panes.instances("memory")
    memory = window.panes.docks[name]
    assert memory.isVisible() and not memory.isFloating(), "in the place that was kept"

    memory.setFloating(True)
    wait_for(space.isVisible)
    memory.setFloating(False)
    wait_for(lambda: not space.isVisible())

    window._close_memory(entry)
    wait_for(space.isVisible)
    assert "Memory" not in [a.text() for a in window.view_menu.actions()], "not a pane"


def test_the_speed_box_says_what_the_default_comes_to_for_each_backend(window):
    bar = window.probe_bar
    assert bar.frequency.itemText(0) == "Default"
    bar.backend.setCurrentIndex(bar.backend.findData("pyocd"))
    assert bar.frequency.itemText(0) == "Default (1 MHz)"
    bar.backend.setCurrentIndex(bar.backend.findData("simulated"))
    idle(window)


def test_another_backend_does_not_keep_the_last_ones_target(window):
    """Reported: the target stayed when Using changed, though each backend
    names targets its own way. Each keeps its own, for switching back."""
    bar = window.probe_bar
    bar.choose_target("sim_single")
    bar.backend.setCurrentIndex(bar.backend.findData("pyocd"))
    idle(window)
    assert bar.chosen_target() == ""
    bar.choose_target("cortex_m")
    bar.backend.setCurrentIndex(bar.backend.findData("simulated"))
    idle(window)
    assert bar.chosen_target() == "sim_single"
    bar.backend.setCurrentIndex(bar.backend.findData("pyocd"))
    idle(window)
    assert bar.chosen_target() == "cortex_m"
    bar.backend.setCurrentIndex(bar.backend.findData("simulated"))
    idle(window)


def test_find_probes_looks_again_and_an_empty_list_does_when_opened(window, monkeypatch):
    bar = window.probe_bar
    assert bar.refresh.text() == "Find probes"
    asked = []
    monkeypatch.setattr(window.flasher, "refresh_probes", lambda: asked.append(True))
    bar.probe.opening.emit()
    assert asked == [], "a list with probes in it is not looked at again on opening"
    bar._show_probes([])
    assert bar.probe.currentText() == probe_bar.NO_PROBES
    bar.probe.opening.emit()
    assert asked == [True]


def test_looking_for_probes_is_shown_while_it_goes_on(window, monkeypatch):
    from pyflashgui.backends.base import BackendError

    bar = window.probe_bar
    seen = []
    window.flasher.looking_for_probes.connect(seen.append)
    bar._show_probes([])
    bar.refresh.click()
    assert bar.refresh.text() == "Looking..." and not bar.refresh.isEnabled()
    assert bar.probe.currentText() == probe_bar.LOOKING, "an empty list says what is happening"
    wait_for(lambda: seen == [True, False])
    assert bar.refresh.text() == "Find probes" and bar.refresh.isEnabled()
    assert bar.chosen_probe() == PROBE

    # Failing ends the looking as well, and says why.
    backend = window.flasher.backend

    def fails():
        raise BackendError("The USB driver is not answering.")

    monkeypatch.setattr(backend, "probes", fails)
    bar.refresh.click()
    wait_for(lambda: seen[-1] is False and len(seen) == 4)
    assert bar.refresh.isEnabled() and bar.probe.currentText() == probe_bar.NO_PROBES
    assert said(window, WARNING)[-1] == "The USB driver is not answering."
