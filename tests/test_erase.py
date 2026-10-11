# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Erasing part of a target's flash, and the line that says what a target is."""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QSettings, Qt
from PySide6.QtWidgets import QMessageBox

from pyflashgui import backends
from pyflashgui.backends.base import BackendError, TargetInfo
from pyflashgui.core.images import BINARY, Image, Segment
from pyflashgui.core.memory_map import FLASH, RAM, Region, lay_out
from pyflashgui.ui.erase_dialog import EraseDialog
from pyflashgui.ui.main_window import describe_device
from pyflashgui.ui.map_view import usage_text

PROBE = "SIM0001"
FLASH_AT = 0x0800_0000


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


# --- a backend ------------------------------------------------------------------------
@pytest.fixture
def connection():
    with backends.get("simulated").connect(PROBE, "sim_single") as made:
        made.program([Segment(FLASH_AT, bytes(0x4000))])
        yield made


def test_a_range_is_erased_a_sector_at_a_time(connection):
    connection.erase_ranges([(FLASH_AT + 0x1800, 0x10)])
    assert connection.read(FLASH_AT, 0x1000) == bytes(0x1000), "the sector before is kept"
    assert connection.read(FLASH_AT + 0x1000, 0x1000) == b"\xff" * 0x1000, "all of its own goes"
    assert connection.read(FLASH_AT + 0x2000, 0x2000) == bytes(0x2000)


def test_several_ranges_and_one_that_crosses_a_sector(connection):
    connection.erase_ranges([(FLASH_AT, 1), (FLASH_AT + 0x2FFF, 2)])
    assert connection.read(FLASH_AT, 0x1000) == b"\xff" * 0x1000
    assert connection.read(FLASH_AT + 0x1000, 0x1000) == bytes(0x1000)
    assert connection.read(FLASH_AT + 0x2000, 0x2000) == b"\xff" * 0x2000


def test_what_is_not_flash_is_not_erased_and_nor_is_anything_else(connection):
    with pytest.raises(BackendError, match="ram is not flash"):
        connection.erase_ranges([(FLASH_AT, 0x1000), (0x2000_0000, 0x10)])
    with pytest.raises(BackendError, match="no memory at 40000000"):
        connection.erase_ranges([(0x4000_0000, 0x10)])
    assert connection.read(FLASH_AT, 0x1000) == bytes(0x1000), "left as it was"


# --- the dialog -----------------------------------------------------------------------
REGIONS = [
    Region("boot", 0x0, 0x8000, FLASH, sector_size=0x400),
    Region("application", 0x1000_0000, 0x10_0000, FLASH, sector_size=0x1000),
    Region("mirror", 0x1100_0000, 0x10_0000, "rom", alias_of="application"),
    Region("ram", 0x2000_0000, 0x2_0000, RAM),
]


def test_the_dialog_opens_on_all_of_the_flash(app):
    dialog = EraseDialog(REGIONS)
    assert dialog.everything.isChecked()
    assert dialog.chosen() == (True, None)
    listed = [dialog.regions.item(i).text() for i in range(dialog.regions.count())]
    assert listed == ["boot: 32.0 KiB at 00000000", "application: 1.0 MiB at 10000000"], (
        "the flash, and neither RAM nor a second address for the same flash"
    )


def test_ticking_a_region_is_choosing_to_erase_by_region(app):
    dialog = EraseDialog(REGIONS)
    dialog.regions.item(1).setCheckState(Qt.Checked)
    assert dialog.some.isChecked()
    assert dialog.chosen() == (True, [(0x1000_0000, 0x10_0000)])
    dialog.regions.item(0).setCheckState(Qt.Checked)
    assert dialog.chosen() == (True, [(0x0, 0x8000), (0x1000_0000, 0x10_0000)])


def test_regions_chosen_with_none_ticked_will_not_do(app):
    dialog = EraseDialog(REGIONS)
    dialog.some.setChecked(True)
    assert dialog.chosen() == (False, None)
    assert dialog.problem.text() == "Tick the regions to erase."


def test_a_range_is_an_address_and_a_length(app):
    dialog = EraseDialog(REGIONS)
    dialog.range.setChecked(True)
    assert dialog.chosen()[0] is False and "address wants" in dialog.problem.text()
    dialog.address.setText("0x1002_0000")
    dialog.length.setText("0")
    assert dialog.chosen()[0] is False and "length wants" in dialog.problem.text()
    dialog.length.setText("54000")
    assert dialog.chosen() == (True, [(0x1002_0000, 0x5_4000)])
    assert dialog.problem.text() == ""


def test_with_no_regions_known_there_is_all_of_it_or_a_range(app):
    dialog = EraseDialog([])
    assert dialog.regions.count() == 0 and dialog.chosen() == (True, None)
    dialog.range.setChecked(True)
    dialog.address.setText("08000000")
    dialog.length.setText("1000")
    assert dialog.chosen() == (True, [(FLASH_AT, 0x1000)])


# --- through the Files pane -----------------------------------------------------------
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
    made.probe_bar.button.click()
    wait_for(lambda: made.flasher.connected)
    made.flasher.program(
        [Image("a.bin", BINARY, (Segment(FLASH_AT, bytes(0x3000)),))], verify=False, reset=False
    )
    wait_for(lambda: not made.flasher.busy)
    yield made
    wait_for(lambda: not made.flasher.busy)
    made.close()


def erase(window, monkeypatch, choose) -> None:
    """Press Erase... and make this choice in the dialog."""

    def answer(dialog):
        choose(dialog)
        return EraseDialog.Accepted

    monkeypatch.setattr(EraseDialog, "exec", answer)
    window.files_view.erase_button.click()
    wait_for(lambda: not window.flasher.busy)
    QCoreApplication.processEvents()


def flash(window) -> bytearray:
    return backends.get("simulated").board(PROBE).memory["flash"]


def test_erase_opens_on_everything_and_erases_it(window, monkeypatch):
    erase(window, monkeypatch, lambda dialog: None)
    assert bytes(flash(window)[:0x3000]) == b"\xff" * 0x3000
    assert window.said[-1][1].startswith("Erased all of the flash of sim_single in ")


def test_a_range_erases_its_sectors_and_says_which_addresses(window, monkeypatch):
    def a_range(dialog):
        dialog.range.setChecked(True)
        dialog.address.setText("08001000")
        dialog.length.setText("1000")

    erase(window, monkeypatch, a_range)
    assert bytes(flash(window)[:0x1000]) == bytes(0x1000)
    assert bytes(flash(window)[0x1000:0x2000]) == b"\xff" * 0x1000
    assert bytes(flash(window)[0x2000:0x3000]) == bytes(0x1000)
    assert window.said[-1][1].startswith("Erased 08001000 to 08001FFF of sim_single in ")


def test_a_region_ticked_is_erased_whole(window, monkeypatch):
    erase(window, monkeypatch, lambda dialog: dialog.regions.item(0).setCheckState(Qt.Checked))
    assert bytes(flash(window)[:0x3000]) == b"\xff" * 0x3000
    assert "Erased 08000000 to 0803FFFF of sim_single" in window.said[-1][1]


def test_a_range_that_is_not_flash_is_an_error_and_nothing_is_erased(window, monkeypatch):
    def ram(dialog):
        dialog.range.setChecked(True)
        dialog.address.setText("20000000")
        dialog.length.setText("100")

    erase(window, monkeypatch, ram)
    assert window.said[-1] == ("error", "ram is not flash, and cannot be erased.")
    assert bytes(flash(window)[:0x3000]) == bytes(0x3000)


def test_a_real_target_is_asked_what_exactly_is_to_go(window, monkeypatch):
    asked = []

    def answer(box):
        asked.append((box.text(), box.informativeText()))
        return QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, "exec", answer)
    monkeypatch.setattr(type(window.flasher.backend), "name", "pyocd")

    def a_range(dialog):
        dialog.range.setChecked(True)
        dialog.address.setText("08001000")
        dialog.length.setText("800")

    erase(window, monkeypatch, a_range)
    assert asked[0][0] == "Erase part of the flash of sim_single?"
    assert "08001000 to 080017FF" in asked[0][1] and "every sector" in asked[0][1]
    assert bytes(flash(window)[0x1000:0x1800]) == bytes(0x800), "and Cancel means nothing goes"


def test_cancelling_the_dialog_erases_nothing(window, monkeypatch):
    monkeypatch.setattr(EraseDialog, "exec", lambda dialog: EraseDialog.Rejected)
    window.files_view.erase_button.click()
    assert not window.flasher.busy and bytes(flash(window)[:0x10]) == bytes(0x10)


# --- a list of memory that may not be all of it ---------------------------------------
def test_outside_a_complete_map_is_an_error_and_outside_a_partial_one_a_warning():
    regions = [Region("Flash 0", 0x0C00_0000, 0x10_0000, FLASH)]
    elsewhere = Image("app.hex", BINARY, (Segment(0x0800_0000, bytes(16)),))
    assert not lay_out([elsewhere], regions).programmable
    partial = lay_out([elsewhere], regions, complete=False)
    assert partial.programmable and [p.level for p in partial.problems] == ["warning"]
    assert partial.problems[0].message == (
        "app.hex: 16 bytes at 08000000 to 0800000F are outside the memory listed for this "
        "target, which may not be all of it."
    )


def test_two_files_on_the_same_bytes_are_an_error_whatever_the_map():
    regions = [Region("Flash 0", 0x0C00_0000, 0x10_0000, FLASH)]
    both = [
        Image("a.hex", BINARY, (Segment(0x0C00_0000, bytes(16)),)),
        Image("b.hex", BINARY, (Segment(0x0C00_0008, bytes(16)),)),
    ]
    assert not lay_out(both, regions, complete=False).programmable


def test_what_is_erased_is_not_guessed_where_the_sectors_are_not_known():
    assert usage_text(0x1800, 0x4_0000, 2, 0x2000) == (
        "6.0 KiB of 256.0 KiB (2.3 %), erasing 2 sectors, 8.0 KiB"
    )
    assert usage_text(0x1800, 0x4_0000, 0, 0) == "6.0 KiB of 256.0 KiB (2.3 %)"
    known = [Region("Flash 0", 0x0, 0x4_0000, FLASH)]
    layout = lay_out([Image("a.bin", BINARY, (Segment(0x0, bytes(0x1800)),))], known)
    assert (layout.usage[0].used, layout.usage[0].sectors) == (0x1800, 0)


# --- what a target is -----------------------------------------------------------------
def test_a_target_is_described_by_what_is_known_of_it():
    regions = [
        Region("Flash 0", 0x0040_0000, 0x8_0000, FLASH),
        Region("Flash 1", 0x1000_0000, 0x1_0000, FLASH),
        Region("mirror", 0x1100_0000, 0x1_0000, "rom", alias_of="Flash 1"),
        Region("RAM 0", 0x2000_0000, 0x8000, RAM),
    ]
    info = TargetInfo("S32K310", vendor="NXP", core="Cortex-M7")
    assert describe_device("S32K310", info, regions) == (
        "S32K310: NXP | Cortex-M7 | flash 576.0 KiB | RAM 32.0 KiB"
    )
    assert describe_device("rp2350", TargetInfo("rp2350", vendor="Raspberry Pi"), []) == (
        "rp2350: Raspberry Pi"
    )
    assert describe_device("typed_in", None, []) == "", "nothing known is nothing said"
    assert describe_device("", info, regions) == ""


def test_the_status_bar_says_what_the_chosen_target_is(window):
    assert window.device_label.text() == ("sim_single: pyflashgui | flash 256.0 KiB | RAM 64.0 KiB")
    window.probe_bar.button.click()  # disconnect, so that another can be chosen
    wait_for(lambda: not window.flasher.connected)
    window.probe_bar.target.setEditText("sim_dual")
    wait_for(lambda: window.device_label.text().startswith("sim_dual: "))
    assert "flash 1.0 MiB" in window.device_label.text()
