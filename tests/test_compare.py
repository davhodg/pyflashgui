# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What was read from a target, compared with what a file says should be there."""

import time

import bincopy
import pytest
from PySide6.QtCore import QCoreApplication, QItemSelectionModel, QSettings, Qt

from pyflashgui.core.compare import compare
from pyflashgui.core.images import BINARY, Image, Segment
from pyflashgui.ui.memory_view import FILE, comparison_text, difference_text

BASE = 0x0800_0000
PROBE = "SIM0001"


def image(*runs: tuple[int, bytes]) -> Image:
    return Image("app.hex", BINARY, tuple(Segment(address, data) for address, data in runs))


def pattern(length: int) -> bytes:
    return bytes(i % 251 for i in range(length))


# --- the comparison itself ------------------------------------------------------------
def test_a_file_that_matches_what_was_read_differs_nowhere():
    data = pattern(0x100)
    made = compare(BASE, data, image((BASE, data)))
    assert (made.compared, made.different, made.first) == (0x100, 0, None)
    assert made.outside == 0 and made.unmentioned == 0
    assert comparison_text(made) == "Compared with app.hex: 256 bytes compared, all the same."


def test_the_bytes_that_differ_are_counted_and_the_first_is_found():
    data = bytearray(pattern(0x100))
    wanted = bytes(data)
    for at in (0x23, 0x24, 0x80):
        data[at] ^= 0xFF
    made = compare(BASE, bytes(data), image((BASE, wanted)))
    assert (made.different, made.first) == (3, 0x23)
    assert made.run_from(0x23) == 2 and made.run_from(0x80) == 1
    assert comparison_text(made) == (
        "Compared with app.hex: 3 bytes differ of 256 bytes, the first at 08000023."
    )


def test_only_where_the_file_and_the_read_overlap_is_compared():
    """Flash the file does not mention is not flash the file says is wrong."""
    data = b"\xff" * 0x40
    made = compare(BASE + 0x20, data, image((BASE, b"\xff" * 0x30), (BASE + 0x1000, b"\x00" * 8)))
    assert made.compared == 0x10, "the sixteen bytes both have"
    assert made.different == 0
    assert made.outside == 0x20 + 8, "what the file has before the read, and far after it"
    assert made.unmentioned == 0x30, "what was read that the file says nothing about"
    assert comparison_text(made) == (
        "Compared with app.hex: 16 bytes compared, all the same. "
        "40 bytes of app.hex are outside what is shown here. "
        "48 bytes of what is shown here are not in app.hex."
    )


def test_a_file_for_somewhere_else_altogether_is_said_and_is_not_all_the_same():
    made = compare(BASE, bytes(16), image((0x2000_0000, bytes(16))))
    assert made.compared == 0 and made.different == 0
    assert comparison_text(made) == (
        "Compared with app.hex: none of it is at the addresses shown here, so there was "
        "nothing to compare."
    )


def test_a_file_in_two_pieces_with_a_gap_between():
    data = bytearray(0x30)
    data[0x25] = 0x99
    made = compare(BASE, bytes(data), image((BASE, bytes(0x10)), (BASE + 0x20, bytes(0x10))))
    assert made.compared == 0x20 and made.unmentioned == 0x10
    assert (made.different, made.first) == (1, 0x25)
    assert made.covered[0x10:0x20] == bytes(0x10), "the gap is not covered, and not a difference"


def test_going_from_one_difference_to_the_next_and_round():
    data = bytearray(0x100)
    for start, length in ((0x10, 3), (0x40, 1), (0xF0, 0x10)):
        data[start : start + length] = b"\x55" * length
    made = compare(BASE, bytes(data), image((BASE, bytes(0x100))))
    assert made.next_run(None) == 0x10
    assert made.next_run(0x10) == 0x40, "the next stretch, not the next byte of this one"
    assert made.next_run(0x40) == 0xF0
    assert made.next_run(0xF0) == 0x10, "round from the last, which runs to the end"
    assert made.previous_run(0x10) == 0xF0, "and round the other way"
    assert made.previous_run(0xF0) == 0x40
    assert made.previous_run(0x40) == 0x10
    assert made.previous_run(None) == 0xF0


def test_with_nothing_different_there_is_nowhere_to_go():
    made = compare(BASE, bytes(16), image((BASE, bytes(16))))
    assert made.next_run(None) is None and made.previous_run(None) is None


def test_a_difference_at_the_very_start():
    made = compare(BASE, b"\x01" + bytes(15), image((BASE, bytes(16))))
    assert made.first == 0 and made.next_run(0) == 0 and made.previous_run(0) == 0


def test_a_whole_flash_is_compared_without_keeping_anybody_waiting():
    data = bytes(8 * 1024 * 1024)
    wanted = bytearray(data)
    wanted[-1] = 1
    started = time.monotonic()
    made = compare(0x1000_0000, data, image((0x1000_0000, bytes(wanted))))
    assert (made.different, made.first) == (1, len(data) - 1)
    assert time.monotonic() - started < 2.0


def test_a_difference_is_said_with_both_sides_of_it():
    data = bytearray(0x40)
    data[0x10:0x12] = b"\xff\xff"
    wanted = bytearray(0x40)
    wanted[0x10:0x12] = b"\x12\x34"
    made = compare(BASE, bytes(data), image((BASE, bytes(wanted))))
    assert difference_text(made, bytes(data), 0x10) == (
        "Differs at 08000010 for 2 bytes: here it is FF FF, in app.hex 12 34."
    )
    long = compare(BASE, b"\xff" * 0x40, image((BASE, bytes(0x40))))
    assert difference_text(long, b"\xff" * 0x40, 0) == (
        "Differs at 08000000 for 64 bytes: here it is FF FF FF FF FF FF FF FF ..., "
        "in app.hex 00 00 00 00 00 00 00 00 ...."
    )


# --- in the Memory pane ---------------------------------------------------------------
def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


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
    # What a test read it has no use for: gone without the question a
    # person would be asked.
    for entry in made.files_view.entries:
        entry.unsaved = False
    made.close()


@pytest.fixture
def memory(window):
    """A Memory pane holding 256 bytes of a pattern, as if just read."""
    window._show_memory(BASE, pattern(0x100), "sim_single")
    return window.memory_view


def hex_file(folder, name: str, address: int, data: bytes) -> str:
    made = bincopy.BinFile()
    made.add_binary(data, address=address)
    path = folder / name
    path.write_text(made.as_ihex())
    return str(path)


def select(files, *rows: int) -> None:
    """Select these rows of the Files list, and no others."""
    files.table.clearSelection()
    for row in rows:
        files.table.selectionModel().select(
            files.table.model().index(row, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )


def compare_with(window, path: str) -> None:
    """Add a file to the list, select it and the read above it, and press Compare."""
    files = window.files_view
    files.add_files([path])
    select(files, 0, len(files.entries) - 1)
    files.compare_button.click()


def selected_row(view) -> int:
    return view.table.selectionModel().selectedRows()[0].row()


def test_nothing_about_a_comparison_shows_until_there_is_one(window, memory):
    view = window.memory_view
    assert view.table.isColumnHidden(FILE)
    assert view.compared.isHidden() and view.next_difference.isHidden()


def test_there_is_nothing_to_compare_before_anything_is_read(window):
    assert not window.files_view.compare_button.isEnabled()


def test_a_file_that_matches_says_so_and_has_nowhere_to_go(window, memory, tmp_path):
    compare_with(window, hex_file(tmp_path, "same.hex", BASE, pattern(0x100)))
    assert memory.compared.text() == "Compared with same.hex: 256 bytes compared, all the same."
    # Said in the log with what was compared with what, since there may be several.
    assert window.said[-1] == (
        "good",
        "Comparison result for Read 1 against same.hex: 256 bytes compared, all the same.",
    )
    assert not memory.table.isColumnHidden(FILE)
    assert not memory.next_difference.isEnabled() and not memory.previous_difference.isEnabled()
    assert memory.model.file_row(0) == "", "a row that agrees has nothing to say"


def test_a_file_that_differs_is_marked_where_it_differs(window, memory, tmp_path):
    wanted = bytearray(pattern(0x100))
    wanted[0x23:0x25] = b"\xaa\xbb"
    wanted[0x80] = 0x00 if wanted[0x80] else 0x01
    compare_with(window, hex_file(tmp_path, "new.hex", BASE, bytes(wanted)))
    assert memory.compared.text() == (
        "Compared with new.hex: 3 bytes differ of 256 bytes, the first at 08000023."
    )
    assert window.said[-1][0] == "error"
    # The first difference is gone to straight away, and said with both sides.
    assert selected_row(memory) == 2
    assert memory.found.text() == (
        "Differs at 08000023 for 2 bytes: here it is 23 24, in new.hex AA BB."
    )
    # Only what differs is spelled out, with a mark for each byte that agrees.
    assert memory.model.file_row(2) == ".. .. .. AA BB .. .. ..  .. .. .. .. .. .. .. .."
    assert memory.model.data(memory.model.index(2, FILE)) == memory.model.file_row(2)
    assert memory.model.file_row(1) == ""

    memory.next_difference.click()
    assert selected_row(memory) == 8 and memory.found.text().startswith("Differs at 08000080 for 1")
    memory.next_difference.click()
    assert selected_row(memory) == 2, "round to the first again"
    memory.previous_difference.click()
    assert selected_row(memory) == 8


def test_a_file_that_covers_part_of_what_was_read_is_compared_over_that_part(
    window, memory, tmp_path
):
    wanted = bytearray(pattern(0x100)[0x40:0x60])
    wanted[5] ^= 0xFF
    compare_with(window, hex_file(tmp_path, "part.hex", BASE + 0x40, bytes(wanted)))
    assert memory.compared.text() == (
        "Compared with part.hex: 1 byte differs of 32 bytes, the first at 08000045. "
        "224 bytes of what is shown here are not in part.hex."
    )
    # On the row that differs, the file's own bytes; and on the row before
    # the file starts, nothing, because nothing there differs.
    assert memory.model.file_row(4).split()[5] != ".."
    assert memory.model.file_row(3) == ""


def test_a_byte_the_file_does_not_mention_is_marked_as_that_on_a_row_that_differs(
    window, memory, tmp_path
):
    wanted = bytearray(pattern(0x100)[0x48:0x50])
    wanted[0] ^= 0xFF
    compare_with(window, hex_file(tmp_path, "tail.hex", BASE + 0x48, bytes(wanted)))
    cells = memory.model.file_row(4).split()
    assert cells[:8] == ["--"] * 8, "the half of the row the file says nothing about"
    assert cells[8] not in ("..", "--") and cells[9:] == [".."] * 7


def test_two_reads_are_compared_and_the_higher_in_the_list_is_the_one_shown(window, memory):
    other = bytearray(pattern(0x100))
    other[7] ^= 0xFF
    window._show_memory(BASE, bytes(other), "sim_single")
    select(window.files_view, 0, 1)
    window.files_view.compare_button.click()
    assert memory.compared.text() == (
        "Compared with Read 2: 1 byte differs of 256 bytes, the first at 08000007."
    )
    assert memory.model.headerData(FILE, Qt.Horizontal) == "Read 2"
    # The other, open in a pane of its own, is marked against the first, and the
    # log says it once.
    other = window.memory_views[1]
    assert other.compared.text() == (
        "Compared with Read 1: 1 byte differs of 256 bytes, the first at 08000007."
    )
    assert [m for _level, m in window.said].count(
        "Comparison result for Read 1 against Read 2: 1 byte differs of 256 bytes, the first "
        "at 08000007."
    ) == 1


def test_of_a_read_and_a_file_it_is_the_read_that_is_shown(window, tmp_path):
    """Whichever is higher in the list: the file is what the target is held against."""
    window.files_view.add_files([hex_file(tmp_path, "app.hex", BASE, pattern(0x100))])
    window._show_memory(BASE, pattern(0x100), "sim_single")
    select(window.files_view, 0, 1)
    window.files_view.compare_button.click()
    of_file, of_read = window.memory_views
    assert of_file.compared.text() == "Compared with Read 1: 256 bytes compared, all the same."
    assert of_read.compared.text() == "Compared with app.hex: 256 bytes compared, all the same."


def test_two_files_are_compared_piece_by_piece(window, tmp_path):
    made = bincopy.BinFile()
    made.add_binary(pattern(0x20), address=BASE)
    made.add_binary(pattern(0x20), address=BASE + 0x1000)
    (tmp_path / "two.hex").write_text(made.as_ihex())
    other = bytearray(pattern(0x20))
    other[3] ^= 0xFF
    window.files_view.add_files(
        [str(tmp_path / "two.hex"), hex_file(tmp_path, "high.hex", BASE + 0x1000, bytes(other))]
    )
    select(window.files_view, 0, 1)
    window.files_view.compare_button.click()
    view = window.memory_views[0]
    assert view.summary.text() == (
        "two.hex: Intel HEX, 64 bytes from 08000000 to 0800101F, in 2 pieces."
    )
    assert view.compared.text() == (
        "Compared with high.hex: 1 byte differs of 32 bytes, the first at 08001003. "
        "32 bytes of what is shown here are not in high.hex."
    )
    assert view.model.row(2)[0] == "08001000", "the second piece starts a row of its own"
    assert selected_row(view) == 2
    assert not view.save_button.isEnabled(), "what is in pieces is not saved as one run"


def test_a_file_for_somewhere_else_is_a_warning(window, memory, tmp_path):
    compare_with(window, hex_file(tmp_path, "ram.hex", 0x2000_0000, bytes(16)))
    assert window.said[-1][0] == "warning"
    assert "nothing to compare" in memory.compared.text()
    assert not memory.next_difference.isEnabled()


def test_a_file_that_cannot_be_read_is_said_and_nothing_is_marked(window, memory, tmp_path):
    bad = tmp_path / "bad.hex"
    bad.write_text(":00000001FE\n:nonsense\n")
    compare_with(window, str(bad))
    assert window.said[-1][0] == "error" and "bad.hex cannot be read" in window.said[-1][1]
    assert memory.table.isColumnHidden(FILE)


def test_a_new_read_puts_the_comparison_away(window, memory, tmp_path):
    compare_with(window, hex_file(tmp_path, "same.hex", BASE, pattern(0x100)))
    assert not memory.table.isColumnHidden(FILE)
    memory.show_memory(BASE, pattern(0x80), "sim_single")
    assert memory.table.isColumnHidden(FILE) and memory.compared.isHidden()
    assert memory.model.comparison is None


def test_compare_waits_for_two_to_be_selected(window, memory, tmp_path):
    files = window.files_view
    assert not files.compare_button.isEnabled()
    select(files, 0)
    assert not files.compare_button.isEnabled()
    files.add_files([hex_file(tmp_path, "same.hex", BASE, pattern(0x100))])
    select(files, 0, 1)
    assert files.compare_button.isEnabled()
