# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Reading a target's memory back into a file."""

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
    events.posted.connect(lambda message, level: made.said.append((level, message)))
    made.connect_to(PROBE, "sim_single")
    wait_for(lambda: made.connected)
    yield made
    made.shutdown()


def finish(flasher) -> None:
    wait_for(lambda: not flasher.busy)
    QCoreApplication.processEvents()


def test_reading_back_saves_what_is_in_the_target_and_says_so(flasher, tmp_path):
    data = pattern(5000)
    flasher.program([images.Image("a.bin", images.BINARY, (Segment(FLASH_AT, data),))], reset=False)
    finish(flasher)
    path = tmp_path / "read.hex"
    flasher.read_back(FLASH_AT, 5000, str(path))
    finish(flasher)
    assert images.read(str(path)).segments == (Segment(FLASH_AT, data),)
    level, line = flasher.said[-1]
    assert level == "good"
    assert line == (
        f"Read 4.9 KiB at 08000000 of sim_single, and saved 4.9 KiB as Intel HEX in {path}."
    )


def test_the_erased_bytes_at_the_end_can_be_left_off(flasher, tmp_path):
    flasher.program(
        [images.Image("a.bin", images.BINARY, (Segment(FLASH_AT, b"\x01\xff\x02"),))], reset=False
    )
    finish(flasher)
    whole, trimmed = tmp_path / "whole.bin", tmp_path / "trimmed.bin"
    flasher.read_back(FLASH_AT, 0x100, str(whole))
    finish(flasher)
    flasher.read_back(FLASH_AT, 0x100, str(trimmed), trim=True)
    finish(flasher)
    assert whole.read_bytes() == b"\x01\xff\x02" + b"\xff" * 0xFD
    assert trimmed.read_bytes() == b"\x01\xff\x02", "an FF in the middle is part of what is there"
    assert "saved 3 bytes as raw binary" in flasher.said[-1][1]


def test_flash_that_is_all_erased_saves_nothing_and_says_why(flasher, tmp_path):
    path = tmp_path / "empty.bin"
    flasher.read_back(FLASH_AT, 0x100, str(path), trim=True)
    finish(flasher)
    assert not path.exists()
    assert flasher.said[-1] == (
        "warning",
        "Read 256 bytes at 08000000 of sim_single: all of it is erased, so there was nothing "
        "to save.",
    )


def test_memory_the_target_does_not_have_and_a_file_that_cannot_be_made(flasher, tmp_path):
    flasher.read_back(0x4000_0000, 16, str(tmp_path / "a.bin"))
    finish(flasher)
    assert flasher.said[-1] == ("error", "The target has no memory at 40000000.")
    flasher.read_back(FLASH_AT, 16, str(tmp_path / "nowhere" / "a.bin"))
    finish(flasher)
    assert flasher.said[-1][0] == "error" and flasher.said[-1][1].startswith("Saving to ")


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
    assert dialog.values() == (0x1000_0000, 0x100_0000, True)
    names = [dialog.region.itemText(i).split()[0] for i in range(dialog.region.count())]
    assert names == ["bootrom", "xip", "sram", "Another"], "an alias is not offered twice"


def test_another_region_fills_in_and_both_can_be_typed_over(app):
    dialog = ReadDialog(REGIONS)
    dialog.region.setCurrentIndex(2)
    assert dialog.values() == (0x2000_0000, 0x4_0000, True)
    dialog.length.setText("0x1_0000")
    dialog.trim.setChecked(False)
    assert dialog.values() == (0x2000_0000, 0x1_0000, False)
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
    assert dialog.values() == (0xFFFF_FFF0, 0x10, True) and dialog.problem.text() == ""


def test_with_no_memory_known_the_range_is_typed(app):
    dialog = ReadDialog([])
    assert dialog.address.text() == "" and dialog.values() is None
    dialog.address.setText("0")
    dialog.length.setText("400")
    assert dialog.values() == (0, 0x400, True)


def test_numbers_are_taken_as_they_are_typed():
    assert parse_number("1000") == 0x1000 and parse_number(" 0x1_0000 ") == 0x1_0000
    assert parse_number("") is None and parse_number("lots") is None


# --- from the Files pane --------------------------------------------------------------
def test_read_asks_what_and_where_and_then_reads(app, tmp_path, monkeypatch):
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
        files = window.files_view
        assert not files.read_button.isEnabled(), "there is nothing connected to read from"
        window.probe_bar.button.click()
        wait_for(lambda: window.flasher.connected)
        assert files.read_button.isEnabled()

        saved_as = tmp_path / "out.bin"
        offered = []

        def answer(_parent, _caption, start, _filter="", _selected=""):
            offered.append(Path(start).name)
            return str(saved_as), "Raw binary (*.bin)"

        window.flasher.program(
            [images.Image("a.bin", images.BINARY, (Segment(FLASH_AT, b"firmware"),))],
            reset=False,
        )
        wait_for(lambda: not window.flasher.busy)
        monkeypatch.setattr(ReadDialog, "exec", lambda self: ReadDialog.Accepted)
        monkeypatch.setattr(QFileDialog, "getSaveFileName", answer)
        files.read_button.click()
        wait_for(lambda: not window.flasher.busy and saved_as.exists())
        # The whole of the flash, which is what the dialog opens on, less
        # the erased bytes after what is there.
        assert saved_as.read_bytes() == b"firmware"
        assert offered[0].startswith("sim_single_08000000_") and offered[0].endswith(".bin")
    finally:
        wait_for(lambda: not window.flasher.busy)
        window.close()


def test_an_s_record_is_given_addresses_wide_enough_for_what_it_holds(tmp_path):
    """Flash at 08000000 saved as .s19, which by its name has 16-bit addresses."""
    low, high = str(tmp_path / "low.s19"), str(tmp_path / "high.s19")
    images.write(low, 0x1000, b"\x01\x02")
    images.write(high, FLASH_AT, b"\x01\x02")
    assert Path(low).read_text().splitlines()[0].startswith("S1"), "16-bit, as the name asks"
    assert Path(high).read_text().splitlines()[0].startswith("S3"), "32-bit, as the data needs"
    assert images.read(high).segments == (Segment(FLASH_AT, b"\x01\x02"),)
