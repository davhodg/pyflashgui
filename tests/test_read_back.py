# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Reading a target's memory back, looking at it, and saving it."""

import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QFileDialog

from pyflashgui import backends
from pyflashgui.backends import jlink_backend
from pyflashgui.backends.base import READ_CHUNK, CancelledError
from pyflashgui.core import images
from pyflashgui.core.events import EventLog
from pyflashgui.core.flasher import Flasher
from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import FLASH, RAM, Region
from pyflashgui.ui.memory_view import MemoryModel, text_of
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
    assert flasher.said[-1] == ("good", "Read 4.9 KiB at 08000000 of sim_single.")


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
    assert model.rowCount() == 2 and model.columnCount() == 3
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


def test_the_memory_pane_is_put_away_until_something_is_read(window, monkeypatch):
    memory = window.memory_view
    assert not window.panes.on_screen("memory")
    assert memory.summary.text().startswith("Nothing has been read yet")
    assert not memory.save_button.isEnabled() and not memory.read_button.isEnabled()
    assert not window.files_view.read_button.isEnabled(), "nothing is connected to read from"

    connect_and_program(window, b"firmware")
    assert window.files_view.read_button.isEnabled() and memory.read_button.isEnabled()
    read(window, monkeypatch, "08000000", "20")
    assert window.panes.on_screen("memory"), "and it comes out when there is something in it"
    assert "memory" in window.panes.detached, "in a window of its own"
    assert memory.model.row(0)[2].startswith("firmware")
    assert memory.summary.text().startswith(
        "sim_single: 32 bytes from 08000000 to 0800001F, read at "
    )
    assert memory.save_button.isEnabled()


def test_reading_saves_no_file_until_save_is_pressed(window, monkeypatch, tmp_path):
    connect_and_program(window, b"firmware")
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: asked.append(a) or ("", ""))
    read(window, monkeypatch, "08000000", "100")
    assert asked == [], "a read made to look costs no file, and asks for none"
    assert window.said[-1] == ("good", "Read 256 bytes at 08000000 of sim_single.")


def test_the_dialog_opens_on_the_whole_of_the_flash(window, monkeypatch):
    connect_and_program(window, b"firmware")
    read(window, monkeypatch)
    assert window.memory_view.model.address == FLASH_AT
    assert len(window.memory_view.model.data_read) == 0x4_0000


def test_read_from_the_memory_pane_is_the_same_read(window, monkeypatch):
    connect_and_program(window, b"firmware")
    monkeypatch.setattr(ReadDialog, "exec", lambda dialog: ReadDialog.Accepted)
    window.memory_view.read_button.click()
    wait_for(lambda: not window.flasher.busy and window.memory_view.model.data_read)
    assert window.memory_view.model.data_read[:8] == b"firmware"


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

    whole, trimmed, hexed = tmp_path / "whole.bin", tmp_path / "trimmed.bin", tmp_path / "a.hex"
    save_as(whole)
    assert whole.read_bytes() == b"\x01\xff\x02" + b"\xff" * 0xFD, "what was read, all of it"
    assert offered[0].startswith("sim_single_08000000_") and offered[0].endswith(".bin")
    assert window.said[-1] == (
        "good",
        f"Saved 256 bytes from 08000000 of sim_single as raw binary in {whole}.",
    )

    memory.trim.setChecked(True)
    save_as(trimmed)
    assert trimmed.read_bytes() == b"\x01\xff\x02", "an FF in the middle is part of what is there"

    save_as(hexed)
    assert images.read(str(hexed)).segments == (Segment(FLASH_AT, b"\x01\xff\x02"),)


def test_flash_that_is_all_erased_is_not_saved_as_nothing(window, monkeypatch, tmp_path):
    window.probe_bar.button.click()
    wait_for(lambda: window.flasher.connected)
    read(window, monkeypatch, "08000000", "100")
    memory = window.memory_view
    memory.trim.setChecked(True)
    asked = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: asked.append(a) or ("", ""))
    memory.save_button.click()
    assert asked == [] and window.said[-1][0] == "warning"
    assert "there is nothing to save" in window.said[-1][1]


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
    assert not window.flasher.busy and not window.memory_view.model.data_read


# --- an S-record wide enough ----------------------------------------------------------
def test_an_s_record_is_given_addresses_wide_enough_for_what_it_holds(tmp_path):
    """Flash at 08000000 saved as .s19, which by its name has 16-bit addresses."""
    low, high = str(tmp_path / "low.s19"), str(tmp_path / "high.s19")
    images.write(low, 0x1000, b"\x01\x02")
    images.write(high, FLASH_AT, b"\x01\x02")
    assert Path(low).read_text().splitlines()[0].startswith("S1"), "16-bit, as the name asks"
    assert Path(high).read_text().splitlines()[0].startswith("S3"), "32-bit, as the data needs"
    assert images.read(high).segments == (Segment(FLASH_AT, b"\x01\x02"),)
