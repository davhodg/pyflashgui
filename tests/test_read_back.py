# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Reading a target's memory back, looking at it, and saving it."""

import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QItemSelectionModel, QSettings, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pyflashgui import backends
from pyflashgui.backends import jlink_backend
from pyflashgui.backends.base import READ_CHUNK, CancelledError
from pyflashgui.core import images
from pyflashgui.core.events import EventLog
from pyflashgui.core.flasher import Flasher
from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import FLASH, GENERIC, RAM, Region
from pyflashgui.ui import files_view
from pyflashgui.ui.memory_view import MemoryModel, parse_bytes, text_of
from pyflashgui.ui.read_dialog import ReadDialog, parse_number

PROBE = "SIM0001"
FLASH_AT = 0x0800_0000


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def pattern(length: int) -> bytes:
    return bytes(i % 251 for i in range(length))


# --- writing a file -------------------------------------------------------------------
def test_what_is_written_reads_back_as_what_it_was(tmp_path):
    data = pattern(1000)
    for name, fmt in (("a.hex", images.IHEX), ("a.s37", images.SREC), ("a.s19", images.SREC)):
        path = str(tmp_path / name)
        assert images.write(path, FLASH_AT, data) == fmt
        assert images.read(path).segments == (Segment(FLASH_AT, data),)


def test_a_raw_binary_is_the_bytes_and_nothing_else(tmp_path):
    path = tmp_path / "a.bin"
    assert images.write(str(path), FLASH_AT, b"\x01\x02\x03") == images.BINARY
    assert path.read_bytes() == b"\x01\x02\x03"
    other = tmp_path / "no_suffix"
    assert images.write(str(other), 0, b"\x04") == images.BINARY, "what it is when it does not say"


def test_a_file_that_cannot_be_written_is_an_image_error(tmp_path):
    with pytest.raises(images.ImageError):
        images.write(str(tmp_path / "no" / "such" / "folder" / "a.hex"), 0, b"\x00")


# --- a long run from a backend --------------------------------------------------------
def test_a_long_run_is_read_in_pieces_with_progress():
    backend = backends.get("simulated")
    data = pattern(READ_CHUNK * 2 + 100)
    with backend.connect(PROBE, "sim_single") as connection:
        connection.program([Segment(FLASH_AT, data)])
        seen = []
        assert connection.read_range(FLASH_AT, len(data), seen.append) == data
        assert len(seen) == 3 and seen[-1] == 1.0 and seen == sorted(seen)


def test_reading_stops_when_it_is_asked_to():
    backend = backends.get("simulated")
    with backend.connect(PROBE, "sim_single") as connection:
        asked = []

        def cancelled() -> bool:
            asked.append(1)
            return len(asked) > 1

        with pytest.raises(CancelledError, match="Reading was cancelled"):
            connection.read_range(FLASH_AT, READ_CHUNK * 4, cancelled=cancelled)
        assert len(asked) == 2


def test_commander_is_started_once_for_the_whole_of_it(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("COMMANDER_SIM_HOME", str(tmp_path))
    jlink_backend.set_commander([sys.executable, str(Path(__file__).with_name("commander_sim.py"))])
    try:
        with backends.get("jlink").connect("801012345", "STM32F103ZE") as connection:
            connection.program([Segment(FLASH_AT, b"abcd")])
            before = len(json.loads((tmp_path / "runs.json").read_text()))
            seen = []
            data = connection.read_range(FLASH_AT, READ_CHUNK * 3, seen.append)
            runs = json.loads((tmp_path / "runs.json").read_text())
        assert data[:4] == b"abcd" and len(data) == READ_CHUNK * 3
        assert len(runs) - before == 1
        assert seen == [0.0, 1.0]
    finally:
        jlink_backend.set_commander(None)


# --- through the flasher --------------------------------------------------------------
@pytest.fixture
def flasher(app):
    events = EventLog()
    made = Flasher(events, backend="simulated")
    made.said = []
    made.read = []
    events.posted.connect(lambda message, level: made.said.append((level, message)))
    made.memory_read.connect(
        lambda address, data, target: made.read.append((address, data, target))
    )
    made.connect_to(PROBE, "sim_single")
    wait_for(lambda: made.connected)
    yield made
    made.shutdown()


def finish(flasher) -> None:
    wait_for(lambda: not flasher.busy)
    QCoreApplication.processEvents()


def test_a_read_goes_into_memory_and_is_announced(flasher):
    data = pattern(5000)
    flasher.program([images.Image("a.bin", images.BINARY, (Segment(FLASH_AT, data),))], reset=False)
    finish(flasher)
    flasher.read_memory(FLASH_AT, 5000)
    assert flasher.busy
    finish(flasher)
    assert flasher.read == [(FLASH_AT, data, "sim_single")]
    level, said = flasher.said[-1]
    assert level == "good"
    assert said.startswith("Read 4.9 KiB at 08000000 of sim_single in ")
    assert said.endswith(" s."), "with how long it took"


def test_memory_the_target_does_not_have_is_an_error_and_nothing_is_announced(flasher):
    flasher.read_memory(0x4000_0000, 16)
    finish(flasher)
    assert flasher.said[-1] == ("error", "The target has no memory at 40000000.")
    assert flasher.read == []


def test_nothing_is_read_with_nothing_connected(app):
    events = EventLog()
    said = []
    events.posted.connect(lambda message, level: said.append((level, message)))
    made = Flasher(events, backend="simulated")
    try:
        made.read_memory(FLASH_AT, 16)
        assert not made.busy
        assert said == [("warning", "Reading needs a probe connected to a target first.")]
    finally:
        made.shutdown()


# --- the dialog -----------------------------------------------------------------------
REGIONS = [
    Region("bootrom", 0x0, 0x4000, "rom"),
    Region("xip", 0x1000_0000, 0x100_0000, FLASH, sector_size=0x1000),
    Region("xip_mirror", 0x1100_0000, 0x100_0000, "rom", alias_of="xip"),
    Region("sram", 0x2000_0000, 0x4_0000, RAM),
]


def test_the_dialog_opens_on_the_flash_with_its_address_and_length(app):
    dialog = ReadDialog(REGIONS)
    assert dialog.region.currentText() == "xip (flash, 16.0 MiB at 10000000)"
    assert dialog.address.text() == "10000000" and dialog.length.text() == "1000000"
    assert dialog.size.text() == "16.0 MiB"
    assert dialog.values() == (0x1000_0000, 0x100_0000)
    names = [dialog.region.itemText(i).split()[0] for i in range(dialog.region.count())]
    assert names == ["bootrom", "xip", "sram", "Another"], "an alias is not offered twice"


def test_another_region_fills_in_and_both_can_be_typed_over(app):
    dialog = ReadDialog(REGIONS)
    dialog.region.setCurrentIndex(2)
    assert dialog.values() == (0x2000_0000, 0x4_0000)
    dialog.length.setText("0x1_0000")
    assert dialog.values() == (0x2000_0000, 0x1_0000)
    assert dialog.size.text() == "64.0 KiB"


def test_what_will_not_do_is_said_in_the_dialog(app):
    dialog = ReadDialog(REGIONS)
    dialog.address.setText("somewhere")
    assert dialog.values() is None and "address wants" in dialog.problem.text()
    dialog.address.setText("08000000")
    dialog.length.setText("0")
    assert dialog.values() is None and "length wants" in dialog.problem.text()
    dialog.address.setText("FFFFFFF0")
    dialog.length.setText("100")
    assert dialog.values() is None and "past the end" in dialog.problem.text()
    dialog.length.setText("10")
    assert dialog.values() == (0xFFFF_FFF0, 0x10) and dialog.problem.text() == ""


def test_with_no_memory_known_the_range_is_typed(app):
    dialog = ReadDialog([])
    assert dialog.address.text() == "" and dialog.values() is None
    dialog.address.setText("0")
    dialog.length.setText("400")
    assert dialog.values() == (0, 0x400)


def test_the_cortex_m_address_map_is_not_offered_to_read_whole(app):
    """Half a gigabyte a region: the range is typed instead."""
    dialog = ReadDialog([Region("Code", 0, 0x2000_0000, GENERIC)])
    assert dialog.address.text() == "" and dialog.values() is None


def test_numbers_are_taken_as_they_are_typed():
    assert parse_number("1000") == 0x1000 and parse_number(" 0x1_0000 ") == 0x1_0000
    assert parse_number("") is None and parse_number("lots") is None


def test_leaving_the_device_as_it_is_is_offered_only_where_it_can_be_done(app):
    plain = ReadDialog(REGIONS)
    assert plain.skip_setup.isHidden() and not plain.skips_setup()
    plain.skip_setup.setChecked(True)
    assert not plain.skips_setup(), "a box nobody can see decides nothing"

    offered = ReadDialog(REGIONS, can_skip_setup=True)
    assert not offered.skip_setup.isHidden()
    assert not offered.skips_setup(), "and it is not ticked to begin with"
    offered.skip_setup.setChecked(True)
    assert offered.skips_setup()
    assert offered.values() == (0x1000_0000, 0x100_0000), "what is read is the same either way"


def test_a_backend_that_sets_nothing_up_reads_the_same_when_asked_to_skip_it():
    with backends.get("simulated").connect(PROBE, "sim_single") as connection:
        connection.program([Segment(FLASH_AT, b"abcd")])
        assert connection.read_range(FLASH_AT, 4, skip_setup=True) == b"abcd"


def test_the_tick_reaches_the_backend_through_the_window(app, tmp_path, monkeypatch):
    from pyflashgui.core import workspaces
    from pyflashgui.core.settings import Settings
    from pyflashgui.ui import probe_bar
    from pyflashgui.ui.main_window import MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()
    settings = Settings(workspaces.settings_path())
    settings.set(probe_bar.BACKEND_KEY, "simulated")
    settings.set(probe_bar.TARGET_KEY, "sim_single")
    window = MainWindow()
    window.show()
    try:
        wait_for(lambda: window.probe_bar.chosen_probe() == PROBE and window.flasher.regions)
        window.probe_bar.button.click()
        wait_for(lambda: window.flasher.connected)
        asked = []
        real = type(window.flasher.connection).read_range

        def noted(self, address, length, progress=None, cancelled=None, skip_setup=False):
            asked.append(skip_setup)
            return real(self, address, length)

        monkeypatch.setattr(type(window.flasher.connection), "read_range", noted)
        shown = []

        def answer(dialog):
            shown.append(not dialog.skip_setup.isHidden())
            dialog.skip_setup.setChecked(True)
            dialog.length.setText("10")
            return ReadDialog.Accepted

        monkeypatch.setattr(ReadDialog, "exec", answer)
        window.files_view.read_button.click()
        wait_for(lambda: not window.flasher.busy and asked)
        assert shown == [False] and asked == [False], "not offered, so not asked for"

        monkeypatch.setattr(type(window.flasher.backend), "can_skip_setup", True)
        window.files_view.read_button.click()
        wait_for(lambda: not window.flasher.busy and len(asked) == 2)
        assert shown == [False, True] and asked == [False, True]
    finally:
        wait_for(lambda: not window.flasher.busy)
        window.close()


# --- the Memory pane ------------------------------------------------------------------
def test_a_row_is_an_address_sixteen_bytes_and_what_they_spell():
    model = MemoryModel()
    model.show(0x0800_0000, b"pyflashgui\x00\x01\xff rows" + bytes(range(0x30, 0x35)))
    assert model.rowCount() == 2 and model.columnCount() == 4
    assert model.row(0) == (
        "08000000",
        "70 79 66 6C 61 73 68 67  75 69 00 01 FF 20 72 6F",
        "pyflashgui... ro",
    )
    assert model.row(1) == ("08000010", "77 73 30 31 32 33 34", "ws01234"), "a short last row"
    assert model.data(model.index(1, 0)) == "08000010"
    assert text_of(bytes([0x1F, 0x20, 0x7E, 0x7F, 0x80])) == ". ~.."


def test_a_whole_flash_is_shown_without_being_laid_out_in_advance(app):
    """A million rows, each worked out as it is drawn."""
    model = MemoryModel()
    model.show(0x1000_0000, bytes(16 * 1024 * 1024))
    assert model.rowCount() == 1024 * 1024
    assert model.row(1024 * 1024 - 1)[0] == "10FFFFF0"


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from pyflashgui.core import workspaces
    from pyflashgui.core.settings import Settings
    from pyflashgui.ui import probe_bar
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
    # What a test read it has no use for: gone without the question a
    # person would be asked.
    for entry in made.files_view.entries:
        entry.unsaved = False
    made.close()


def read(window, monkeypatch, address: str = "", length: str = "") -> None:
    """Press Read... in the Files pane and answer the dialog."""

    def answer(dialog):
        if address:
            dialog.address.setText(address)
            dialog.length.setText(length)
        return ReadDialog.Accepted

    monkeypatch.setattr(ReadDialog, "exec", answer)
    window.files_view.read_button.click()
    wait_for(lambda: not window.flasher.busy)
    QCoreApplication.processEvents()


def connect_and_program(window, data: bytes) -> None:
    window.probe_bar.button.click()
    wait_for(lambda: window.flasher.connected)
    window.flasher.program(
        [images.Image("a.bin", images.BINARY, (Segment(FLASH_AT, data),))], reset=False
    )
    wait_for(lambda: not window.flasher.busy)


def test_there_is_no_memory_pane_until_something_is_read(window, monkeypatch):
    assert window.memory_views == [] and window.memory_view is None
    assert "Memory" not in [d.windowTitle() for d in window.panes.docks.values()]
    assert not window.files_view.read_button.isEnabled(), "nothing is connected to read from"

    connect_and_program(window, b"firmware")
    assert window.files_view.read_button.isEnabled()
    read(window, monkeypatch, "08000000", "20")
    assert window.panes.instances("memory") == ["memory"]
    dock = window.panes.docks["memory"]
    assert dock.windowTitle() == "Read 1"
    assert dock.isVisible() and not dock.isFloating(), "beside the Files pane"
    view = window.memory_view
    assert view.model.row(0)[2].startswith("firmware")
    assert view.summary.text().startswith(
        "sim_single: 32 bytes from 08000000 to 0800001F, read at "
    )
    assert view.save_button.isEnabled()
    assert not hasattr(view, "read_button"), "Read... is the Files pane's"


def test_each_read_has_a_pane_of_its_own_numbered_as_it_comes(window, monkeypatch):
    """Two reads are as often wanted side by side as one after the other."""
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    read(window, monkeypatch, "08000004", "4")
    read(window, monkeypatch, "08000000", "2")
    assert window.panes.instances("memory") == ["memory", "memory 2", "memory 3"]
    titles = [window.panes.docks[n].windowTitle() for n in window.panes.instances("memory")]
    assert titles == [
        "Read 1",
        "Read 2",
        "Read 3",
    ]
    first, second, third = window.memory_views
    assert first.model.data_read[:8] == b"firmware", "the first is as it was"
    assert second.model.data_read == b"ware" and third.model.data_read == b"fi"
    assert window.memory_view is third


def test_once_one_is_docked_the_next_is_tabbed_with_it(window, monkeypatch):
    """Put one where it is wanted, and that is where the rest go."""
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    first = window.panes.docks["memory"]
    first.setFloating(False)
    read(window, monkeypatch, "08000000", "8")
    read(window, monkeypatch, "08000000", "4")
    second, third = window.panes.docks["memory 2"], window.panes.docks["memory 3"]
    assert not second.isFloating() and not third.isFloating()
    assert set(window.tabifiedDockWidgets(first)) == {second, third}


def test_a_memory_pane_is_in_the_view_menu_like_any_other(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    QCoreApplication.processEvents()  # the menu is rebuilt a turn of the loop later
    window._tick_view_menu()
    listed = {action.text(): action for action in window.view_menu.actions()}
    assert listed["Read 1"].isChecked()


def test_what_was_read_is_not_kept_with_the_workspace(window, monkeypatch):
    """There would be nothing to put in the pane when it came back."""
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    read(window, monkeypatch, "08000000", "10")
    window.panes.detach("memory 2")
    window.panes.save()
    settings = window.ctx.settings
    assert settings.get("panes.instances", []) == []
    assert settings.get("panes.detached", []) == []
    assert settings.get("panes.detached_at.memory 2") is None


# --- the list it joins, closing its pane, and letting go of it ------------------------
def answer_with(monkeypatch, button) -> list[tuple[str, str]]:
    """Answer every question with this button, and note what was asked."""
    asked = []

    def answer(box):
        asked.append((box.text(), box.informativeText()))
        return button

    monkeypatch.setattr(QMessageBox, "exec", answer)
    return asked


def gone(window, name: str) -> None:
    """Wait for a pane that was closed to be taken away, which is a moment later."""
    wait_for(lambda: name not in window.panes.docks)


def select(files, *rows: int) -> None:
    """Select these rows of the Files list, and no others."""
    files.table.clearSelection()
    for row in rows:
        files.table.selectionModel().select(
            files.table.model().index(row, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )


def test_what_is_read_joins_the_list_unticked_and_not_saved(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    files = window.files_view
    cells = [files.table.item(0, c).text() for c in range(files.table.columnCount())]
    assert cells[0] == "Read 1"
    assert cells[1].startswith("sim_single, read ") and cells[1].endswith(", not saved")
    assert cells[2:] == ["08000000", "0800000F", "16 bytes"]
    assert files.table.item(0, 0).checkState() == Qt.Unchecked, "a read is made to be looked at"
    assert files.loaded() == []
    assert not files.table.item(0, 2).flags() & Qt.ItemIsEditable, "it was read from where it is"
    assert window.ctx.settings.get(files_view.FILES_KEY, []) == [], "and is not kept"


def test_closing_a_pane_asks_nothing_and_what_it_showed_can_be_shown_again(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    asked = answer_with(monkeypatch, QMessageBox.Cancel)
    assert window.panes.docks["memory"].close() is True and asked == []
    gone(window, "memory")
    files = window.files_view
    assert [e.name for e in files.entries] == ["Read 1"] and files.entries[0].unsaved
    assert not files.show_button.isEnabled(), "nothing is selected to show"
    select(files, 0)
    files.show_button.click()
    assert window.panes.instances("memory") == ["memory"]
    assert window.memory_view.model.data_read[:8] == b"firmware"


def test_one_that_is_shown_already_is_brought_forward_and_not_shown_twice(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    read(window, monkeypatch, "08000000", "8")
    files = window.files_view
    files.table.itemDoubleClicked.emit(files.table.item(0, 0))
    assert window.panes.instances("memory") == ["memory", "memory 2"]


def test_closing_one_leaves_the_others_and_their_numbers(window, monkeypatch):
    connect_and_program(window, b"firmware")
    for _ in range(3):
        read(window, monkeypatch, "08000000", "10")
    window.panes.docks["memory 2"].close()
    gone(window, "memory 2")
    assert window.panes.instances("memory") == ["memory", "memory 3"]
    read(window, monkeypatch, "08000000", "10")
    assert window.panes.instances("memory") == ["memory", "memory 3", "memory 2"], (
        "the next takes the number that was given up"
    )
    assert [e.name for e in window.files_view.entries] == ["Read 1", "Read 2", "Read 3", "Read 4"]


def test_removing_a_read_that_was_not_saved_says_so_first(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    files = window.files_view
    asked = answer_with(monkeypatch, QMessageBox.Cancel)
    select(files, 0)
    files.remove_button.click()
    assert asked == [
        (
            "Remove without saving?",
            "Read 1 is what was read from sim_single, and has not been saved. "
            "Without saving, it is thrown away.",
        )
    ]
    QCoreApplication.processEvents()
    assert len(files.entries) == 1 and window.panes.docks["memory"].isVisible(), "Cancel keeps it"


def test_discard_throws_it_away_and_its_pane_with_it(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    files = window.files_view
    asked = answer_with(monkeypatch, QMessageBox.Discard)
    select(files, 0)
    files.remove_button.click()
    gone(window, "memory")
    assert len(asked) == 1 and files.entries == [] and window.memory_view is None
    read(window, monkeypatch, "08000000", "4")
    assert [e.name for e in files.entries] == ["Read 2"], "a name is not used twice"
    assert window.panes.instances("memory") == ["memory"]


def test_save_saves_it_and_then_removes_it(window, monkeypatch, tmp_path):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "8")
    saved_as = tmp_path / "kept.bin"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(saved_as), ""))
    answer_with(monkeypatch, QMessageBox.Save)
    select(window.files_view, 0)
    window.files_view.remove_button.click()
    gone(window, "memory")
    assert saved_as.read_bytes() == b"firmware" and window.files_view.entries == []


def test_a_save_that_was_cancelled_has_saved_nothing_so_it_stays(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    answer_with(monkeypatch, QMessageBox.Save)
    select(window.files_view, 0)
    window.files_view.remove_button.click()
    QCoreApplication.processEvents()
    assert window.panes.instances("memory") == ["memory"] and window.memory_view.unsaved


def test_a_read_that_was_saved_says_so_and_is_removed_without_a_word(window, monkeypatch, tmp_path):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "8")
    files = window.files_view
    saved_as = tmp_path / "kept.hex"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(saved_as), ""))
    window.memory_view.save_button.click()
    assert not window.memory_view.unsaved
    assert not files.table.item(0, 1).text().endswith("not saved")
    asked = answer_with(monkeypatch, QMessageBox.Cancel)
    select(files, 0)
    files.remove_button.click()
    assert asked == [] and files.entries == []
    gone(window, "memory")


def test_a_pane_in_a_window_of_its_own_closes_the_same_way(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "8")
    window.panes.detach("memory")
    asked = answer_with(monkeypatch, QMessageBox.Cancel)
    assert window.panes.detached["memory"].close() is True and asked == []
    gone(window, "memory")
    assert window.memory_views == [] and len(window.files_view.entries) == 1


def test_putting_a_detached_pane_back_in_the_window_is_not_closing_it(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "8")
    window.panes.detach("memory")
    window.panes.attach("memory")
    QCoreApplication.processEvents()
    assert window.panes.instances("memory") == ["memory"]
    assert window.memory_view.model.data_read == b"firmware"


def test_closing_pyflashgui_asks_about_each_and_one_kept_keeps_it_open(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "8")
    read(window, monkeypatch, "08000000", "4")
    # Whether or not its pane is still open: it is the read that would be lost.
    window.panes.docks["memory"].close()
    gone(window, "memory")
    asked = answer_with(monkeypatch, QMessageBox.Cancel)
    assert window.close() is False, "a read that is kept keeps the whole of it open"
    assert len(asked) == 1 and asked[0][0] == "Close without saving?"
    assert len(window.files_view.entries) == 2

    asked = answer_with(monkeypatch, QMessageBox.Discard)
    assert window.close() is True
    assert len(asked) == 2


def test_reading_saves_no_file_until_save_is_pressed(window, monkeypatch, tmp_path):
    connect_and_program(window, b"firmware")
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: asked.append(a) or ("", ""))
    read(window, monkeypatch, "08000000", "100")
    assert asked == [], "a read made to look costs no file, and asks for none"
    assert any(
        level == "good" and said.startswith("Read 256 bytes at 08000000 of sim_single in ")
        for level, said in window.said
    )


def test_the_dialog_opens_on_the_whole_of_the_flash(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch)
    assert window.memory_view.model.address == FLASH_AT
    assert len(window.memory_view.model.data_read) == 0x4_0000


def test_what_is_shown_is_saved_as_it_was_read_by_the_name_it_is_given(
    window, monkeypatch, tmp_path
):
    connect_and_program(window, b"\x01\xff\x02")
    read(window, monkeypatch, "08000000", "100")
    memory = window.memory_view
    offered = []

    def save_as(path):
        def answer(_parent, _caption, start, _filter="", _selected=""):
            offered.append(Path(start).name)
            return str(path), ""

        monkeypatch.setattr(QFileDialog, "getSaveFileName", answer)
        memory.save_button.click()

    whole, hexed = tmp_path / "whole.bin", tmp_path / "a.hex"
    save_as(whole)
    assert whole.read_bytes() == b"\x01\xff\x02" + b"\xff" * 0xFD, "what was read, all of it"
    assert offered[0] == "sim_single_08000000_00000100.bin", "where it starts, and its size"
    assert window.said[-1] == (
        "good",
        f"Saved 256 bytes from 08000000 of sim_single as raw binary in {whole}.",
    )

    save_as(hexed)
    assert images.read(str(hexed)).segments == (
        Segment(FLASH_AT, b"\x01\xff\x02" + b"\xff" * 0xFD),
    )


def crop_with(monkeypatch, memory, choose):
    """Crop... with the dialog answered by ``choose``, which is handed the dialog."""
    from pyflashgui.ui.crop_dialog import CropDialog

    def answer(dialog):
        choose(dialog)
        return CropDialog.Accepted if dialog.result() is not None else CropDialog.Rejected

    monkeypatch.setattr(CropDialog, "exec", answer)
    return memory.crop()


def test_crop_makes_a_read_of_its_own_without_the_erased_end(window, monkeypatch):
    """Asked for: Save said it saved what is shown, and a tick made it save less."""
    connect_and_program(window, b"\x01\xff\x02")
    read(window, monkeypatch, "08000000", "100")
    memory = window.memory_view
    assert crop_with(monkeypatch, memory, lambda dialog: None)
    made = window.files_view.entries[-1]
    assert made.unsaved and made.name == "Read 1 cropped", "named after it, not as a read"
    assert made.cropped_from == "Read 1"
    assert memory.title() == "Read 1"
    assert made.image.segments == (Segment(FLASH_AT, b"\x01\xff\x02"),), "an FF inside is kept"
    assert memory.model.data_read == b"\x01\xff\x02" + b"\xff" * 0xFD, "the first is untouched"
    assert window.said[-1][1].startswith("Cropped Read 1 to 08000000 to 08000002")


def test_crop_takes_a_range(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "100")

    def a_range(dialog):
        dialog.range.setChecked(True)
        dialog.start.setText("08000004")
        dialog.length.setText("4")

    assert crop_with(monkeypatch, window.memory_view, a_range)
    assert window.files_view.entries[-1].image.segments == (Segment(FLASH_AT + 4, b"ware"),)
    assert crop_with(monkeypatch, window.memory_view, a_range)
    assert window.files_view.entries[-1].name == "Read 1 cropped 2", "a second is told apart"


def test_crop_refuses_what_would_leave_nothing_or_run_past_the_end(app):
    from pyflashgui.ui.crop_dialog import CropDialog

    dialog = CropDialog(FLASH_AT, b"\xff" * 16, erased_said=0xFF)
    assert dialog.result() is None and "nothing left" in dialog.problem.text()
    dialog.range.setChecked(True)
    dialog.length.setText("20")
    assert dialog.result() is None and "past the end" in dialog.problem.text()
    dialog.length.setText("10")
    assert dialog.result() == (FLASH_AT, b"\xff" * 16)
    assert dialog.kept.text() == "Keeps 08000000 to 0800000F, 16 bytes."


def test_a_file_that_cannot_be_made_is_said_and_the_read_is_kept(window, monkeypatch, tmp_path):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    nowhere = tmp_path / "no" / "such" / "folder" / "a.bin"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(nowhere), ""))
    window.memory_view.save_button.click()
    assert window.said[-1][0] == "error" and window.said[-1][1].startswith("Saving to ")
    assert window.memory_view.model.data_read[:8] == b"firmware"


def test_cancelling_the_dialog_reads_nothing(window, monkeypatch):
    connect_and_program(window, b"firmware")
    monkeypatch.setattr(ReadDialog, "exec", lambda dialog: ReadDialog.Rejected)
    window.files_view.read_button.click()
    assert not window.flasher.busy and window.memory_views == []


# --- going to an address, and finding something ---------------------------------------
BASE = 0x0800_0000


@pytest.fixture
def memory(window):
    """A Memory pane holding 4 KiB: mostly a pattern, with three things to find."""
    data = bytearray(pattern(0x1000))
    data[0x0123:0x0127] = b"\xde\xad\xbe\xef"
    data[0x0800:0x0804] = b"\xde\xad\xbe\xef"
    data[0x0A00:0x0A08] = b"Firmware"
    window._show_memory(BASE, bytes(data), "sim_single")
    return window.memory_view


def selected_row(view) -> int:
    return view.table.selectionModel().selectedRows()[0].row()


def test_nothing_can_be_looked_for_until_something_is_read(window):
    from pyflashgui.ui.memory_view import MemoryView

    view = MemoryView(window.flasher, window.ctx)
    assert not view.goto.isEnabled() and not view.find.isEnabled()
    assert not view.next_button.isEnabled() and not view.previous_button.isEnabled()
    view.show_memory(BASE, bytes(16), "sim_single")
    assert view.goto.isEnabled() and view.find.isEnabled() and view.next_button.isEnabled()


def test_go_to_selects_the_row_an_address_is_on(memory):
    memory.goto.setText("0800_0A07")
    memory.go_to()
    assert selected_row(memory) == 0xA0 and memory.found.text() == "At 08000A07."
    memory.goto.setText("0x08000000")
    memory.go_to()
    assert selected_row(memory) == 0


def test_an_address_that_was_not_read_is_said_with_what_was(memory):
    memory.goto.setText("08001000")
    memory.go_to()
    assert memory.found.text() == (
        "08001000 is not in what was read, which is 08000000 to 08000FFF."
    )
    memory.goto.setText("up a bit")
    memory.go_to()
    assert memory.found.text() == "'up a bit' is not an address: it wants hexadecimal."


def test_bytes_are_found_however_they_are_typed(memory):
    for typed in ("DE AD BE EF", "deadbeef", "0xDE, 0xAD, 0xBE, 0xEF", "DE_AD BEEF"):
        memory.show_memory(BASE, memory.model.data_read, "sim_single")
        memory.find.setText(typed)
        memory.find_next()
        assert memory.found.text() == "Found at 08000123.", typed
        assert selected_row(memory) == 0x12


def test_next_goes_on_and_round_and_previous_goes_back(memory):
    memory.find.setText("DE AD BE EF")
    memory.find_next()
    memory.find_next()
    assert memory.found.text() == "Found at 08000800." and selected_row(memory) == 0x80
    memory.find_next()
    assert memory.found.text() == "Found at 08000123, having gone round from the end."
    memory.find_previous()
    assert memory.found.text() == "Found at 08000800, having gone round from the start."
    memory.find_previous()
    assert memory.found.text() == "Found at 08000123."


def test_previous_before_anything_is_found_is_the_last_there_is(memory):
    memory.find.setText("DEADBEEF")
    memory.find_previous()
    assert memory.found.text() == "Found at 08000800."


def test_text_is_found_as_it_is_spelled(memory):
    memory.find_as.setCurrentText("Text")
    memory.find.setText("Firmware")
    memory.find_next()
    assert memory.found.text() == "Found at 08000A00." and selected_row(memory) == 0xA0
    memory.find.setText("firmware")
    memory.find_next()
    assert memory.found.text() == "Not found in what was read.", "capitals are part of it"


def test_text_that_looks_like_hexadecimal_is_looked_for_as_what_was_chosen(memory):
    data = bytearray(0x40)
    data[0x10:0x14] = b"BEEF"
    data[0x20:0x22] = b"\xbe\xef"
    memory.show_memory(BASE, bytes(data), "sim_single")
    memory.find.setText("BEEF")
    memory.find_next()
    assert memory.found.text() == "Found at 08000020.", "as bytes, which is what it opens on"
    memory.find_as.setCurrentText("Text")
    memory.find_next()
    assert memory.found.text() == "Found at 08000010."


def test_what_is_not_bytes_says_so_and_points_at_text(memory):
    for typed in ("DE A", "Firmware", "0x"):
        memory.find.setText(typed)
        memory.find_next()
        assert "is not bytes in hexadecimal" in memory.found.text(), typed
        assert "choose Text" in memory.found.text()


def test_a_match_across_two_rows_is_found_and_shown_where_it_starts(memory):
    data = bytearray(0x40)
    data[0x0E:0x12] = b"\x11\x22\x33\x44"
    memory.show_memory(BASE, bytes(data), "sim_single")
    memory.find.setText("11 22 33 44")
    memory.find_next()
    assert memory.found.text() == "Found at 0800000E." and selected_row(memory) == 0


def test_a_new_read_starts_the_search_again(memory):
    memory.find.setText("DEADBEEF")
    memory.find_next()
    memory.find_next()
    assert memory.found.text() == "Found at 08000800."
    memory.show_memory(BASE, memory.model.data_read, "sim_single")
    assert memory.found.text() == ""
    memory.find_next()
    assert memory.found.text() == "Found at 08000123."


def test_enter_in_either_box_does_what_the_box_is_for(memory):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    memory.goto.setText("08000800")
    QTest.keyClick(memory.goto, Qt.Key_Return)
    assert memory.found.text() == "At 08000800."
    memory.find.setText("DEADBEEF")
    QTest.keyClick(memory.find, Qt.Key_Return)
    assert memory.found.text() == "Found at 08000123."
    memory.next_button.click()
    assert memory.found.text() == "Found at 08000800."
    memory.previous_button.click()
    assert memory.found.text() == "Found at 08000123."


def test_bytes_typed_are_read_as_bytes_or_not_at_all():
    assert parse_bytes("DE AD") == b"\xde\xad" and parse_bytes("0x01,0x02") == b"\x01\x02"
    assert parse_bytes("") is None and parse_bytes("   ") is None
    assert parse_bytes("ABC") is None, "half a byte is not a byte"
    assert parse_bytes("GG") is None


# --- an S-record wide enough ----------------------------------------------------------
def test_an_s_record_is_given_addresses_wide_enough_for_what_it_holds(tmp_path):
    """Flash at 08000000 saved as .s19, which by its name has 16-bit addresses."""
    low, high = str(tmp_path / "low.s19"), str(tmp_path / "high.s19")
    images.write(low, 0x1000, b"\x01\x02")
    images.write(high, FLASH_AT, b"\x01\x02")
    assert Path(low).read_text().splitlines()[0].startswith("S1"), "16-bit, as the name asks"
    assert Path(high).read_text().splitlines()[0].startswith("S3"), "32-bit, as the data needs"
    assert images.read(high).segments == (Segment(FLASH_AT, b"\x01\x02"),)


def test_what_erased_reads_as_can_be_chosen_and_is_kept_for_the_target(window, monkeypatch):
    """Reported: an XMC4500's erased flash reads 00, where most devices' reads FF."""
    window.probe_bar.button.click()
    wait_for(lambda: window.flasher.connected)
    board = backends.get("simulated").board(PROBE)
    board.memory["flash"][:256] = b"\x01\x00\x02" + b"\x00" * 0xFD
    read(window, monkeypatch, "08000000", "100")
    memory = window.memory_view
    seen = []

    def zeros(dialog):
        seen.append(dialog.erased_as.itemText(0))
        dialog.erased_as.setCurrentIndex(dialog.erased_as.findData(0x00))

    assert crop_with(monkeypatch, memory, zeros)
    assert seen == ["As the target says (FF)"]
    assert window.files_view.entries[-1].image.segments == (Segment(FLASH_AT, b"\x01\x00\x02"),)
    remembered = []
    crop_with(monkeypatch, memory, lambda dialog: remembered.append(dialog.erased_choice()))
    assert remembered == [0x00], "kept for the target"


def test_a_memory_pane_s_tab_has_close_on_a_right_click(window, monkeypatch):
    """Asked for: with several Memory panes as tabs, closing one by its tab."""
    from PySide6.QtWidgets import QTabBar

    connect_and_program(window, b"firmware")
    read(window, monkeypatch, "08000000", "10")
    read(window, monkeypatch, "08000000", "20")
    first, second = window._memory_panes()
    docks = window.panes.docks

    bar = QTabBar()
    bar.addTab("Event Log")
    bar.addTab(docks[second].windowTitle())
    assert window._memory_tab(bar, 0) == "", "another pane's tab is left to Qt's own menu"
    assert window._memory_tab(bar, 1) == second

    menu = window.memory_tab_menu(second)
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Close", "Close the other Memory panes", "Close all Memory panes"]
    menu.actions()[1].trigger()
    assert not window.panes.on_screen(first) and window.panes.on_screen(second)
    menu = window.memory_tab_menu(second)
    assert not menu.actions()[1].isEnabled(), "no others left to close"
    menu.actions()[0].trigger()
    assert not window.panes.on_screen(second)
    assert len(window.files_view.entries) == 2, "the reads are still on the list"


def test_a_right_click_on_a_memory_tab_reaches_its_menu(window, monkeypatch):
    """The click itself, on the tab bar Qt makes for panes in tabs."""
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QTabBar

    connect_and_program(window, b"firmware")
    window.show()
    for length in ("10", "20", "30"):
        read(window, monkeypatch, "08000000", length)
    QCoreApplication.processEvents()
    titles = {window.panes.docks[n].windowTitle() for n in window._memory_panes()}
    bars = [
        b
        for b in window.findChildren(QTabBar)
        if b.isVisible() and any(b.tabText(i) in titles for i in range(b.count()))
    ]
    if not bars:
        pytest.skip("Qt made no tab bar for the panes on this platform")
    opened = []

    class Shown:
        """The menu, recorded rather than shown: shown, it waits for a click."""

        def __init__(self, name):
            self.name = name

        def exec(self, _where):
            opened.append(self.name)

    monkeypatch.setattr(window, "memory_tab_menu", Shown)
    bar = bars[0]
    index = next(i for i in range(bar.count()) if bar.tabText(i) in titles)
    centre = bar.tabRect(index).center()
    QApplication.sendEvent(
        bar, QContextMenuEvent(QContextMenuEvent.Mouse, centre, bar.mapToGlobal(centre))
    )
    assert opened and opened[0] in window._memory_panes()
