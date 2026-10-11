# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A Memory pane: what one read of a target found, to look at and to save.

A read goes into memory and is shown here, as addresses, bytes and the
characters they spell. Saving it is a second step, taken when it has been
looked at and found worth keeping: most reads are to see what is there, and
a file for each would be a folder of files nobody opens again.

The rows are worked out as they are drawn. A whole flash is a million of
them, and making each one in advance would take longer than reading it did.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core import images
from pyflashgui.core.compare import DIFFERENT, Comparison, compare
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher, size_text
from pyflashgui.core.images import ImageError
from pyflashgui.ui import folders, fonts, messages
from pyflashgui.ui.files_view import parse_address

#: Bytes shown on a row.
WIDTH = 16
ADDRESS, BYTES, TEXT, FILE = range(4)
HEADINGS = ("Address", "Bytes", "Text", "File")

#: In the File column, a byte the file agrees about and one it says
#: nothing about. What is left to read is what differs.
AGREES, UNMENTIONED = "..", "--"
#: How many bytes of a difference are spelled out in the line about it.
MOST_SHOWN = 8

NOTHING = "Nothing has been read yet. Read... reads part of the connected target's memory."
TRIM_TIP = (
    "Erased flash reads as FF. With this ticked, the FF bytes after the last\n"
    "byte that holds something are not saved, so the file is the size of\n"
    "what is there and not the size of what was read."
)


#: What Find looks for: bytes written in hexadecimal, or the characters
#: themselves.
AS_BYTES, AS_TEXT = "Bytes", "Text"

GOTO_TIP = (
    "An address in what was read, in hexadecimal. Enter goes to the row it\n"
    "is on. Ctrl+G comes here."
)
FIND_TIP = (
    "Bytes in hexadecimal, such as DE AD BE EF, or text as it is spelled.\n"
    "Enter finds the next, and the search goes round from the end to the\n"
    "start. Ctrl+F comes here; F3 and Shift+F3 find the next and the one\n"
    "before."
)


def parse_bytes(text: str) -> bytes | None:
    """Bytes as somebody would type them in hexadecimal, or None if they are not.

    Spaces, commas and 0x in front of any of them are all let through:
    DEADBEEF, DE AD BE EF and 0xDE, 0xAD are the same four bytes.
    """
    digits = "".join(
        part[2:] if part.lower().startswith("0x") else part
        for part in text.replace(",", " ").replace("_", "").split()
    )
    if not digits or len(digits) % 2:
        return None
    try:
        return bytes.fromhex(digits)
    except ValueError:
        return None


def comparison_text(made: Comparison) -> str:
    """What comparing found, in a sentence or two."""
    if made.compared == 0:
        return (
            f"Compared with {made.name}: none of it is at the addresses that were read, "
            "so there was nothing to compare."
        )
    if made.different:
        count = "1 byte differs" if made.different == 1 else f"{made.different} bytes differ"
        said = (
            f"Compared with {made.name}: {count} of {size_text(made.compared)}, the first "
            f"at {made.address + made.first:08X}."
        )
    else:
        said = f"Compared with {made.name}: {size_text(made.compared)} compared, all the same."
    # What each has that the other does not is said, and is not a
    # difference: the file was not wrong about what it does not mention.
    if made.outside:
        said += f" {size_text(made.outside)} of the file are outside what was read."
    if made.unmentioned:
        said += f" {size_text(made.unmentioned)} of what was read are not in the file."
    return said


def difference_text(made: Comparison, data: bytes, at: int) -> str:
    """One stretch of differing bytes: where, how long, and both sides of it."""
    length = made.run_from(at)
    shown = min(length, MOST_SHOWN)
    more = " ..." if length > shown else ""
    file = " ".join(f"{b:02X}" for b in made.file[at : at + shown])
    target = " ".join(f"{b:02X}" for b in data[at : at + shown])
    size = "1 byte" if length == 1 else f"{length} bytes"
    return (
        f"Differs at {made.address + at:08X} for {size}: the file has {file}{more}, "
        f"the target {target}{more}."
    )


def text_of(data: bytes) -> str:
    """The characters these bytes spell, with a dot for each that spells none."""
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


class MemoryModel(QAbstractTableModel):
    """Sixteen bytes a row: where they are, what they are, and what they spell."""

    def __init__(self) -> None:
        super().__init__()
        self.address = 0
        self.data_read = b""
        #: What it was last compared with, if anything since it was read.
        self.comparison: Comparison | None = None

    def show(self, address: int, data: bytes) -> None:
        self.beginResetModel()
        self.address, self.data_read = address, data
        # A comparison is of one read, and this is another.
        self.comparison = None
        self.endResetModel()

    def show_comparison(self, comparison: Comparison | None) -> None:
        self.beginResetModel()
        self.comparison = comparison
        self.endResetModel()

    def file_row(self, row: int) -> str:
        """What the file has on a row where it differs, and nothing where it does not.

        Only the bytes that differ are spelled out, with a mark in place
        of each that agrees: sixteen bytes beside sixteen bytes leaves the
        reader to find the one that is not the same.
        """
        made = self.comparison
        start, stop = row * WIDTH, (row + 1) * WIDTH
        if made is None or DIFFERENT not in made.differs[start:stop]:
            return ""
        cells = [
            f"{made.file[at]:02X}"
            if made.differs[at]
            else AGREES
            if made.covered[at]
            else UNMENTIONED
            for at in range(start, min(stop, len(made.differs)))
        ]
        halves = (cells[: WIDTH // 2], cells[WIDTH // 2 :])
        return "  ".join(" ".join(half) for half in halves if half)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else -(-len(self.data_read) // WIDTH)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADINGS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return HEADINGS[section]
        return None

    def row(self, row: int) -> tuple[str, str, str]:
        """One row as it is shown: its address, its bytes and their text."""
        chunk = self.data_read[row * WIDTH : (row + 1) * WIDTH]
        # A gap after the eighth, so that a byte can be found by eye.
        halves = (chunk[: WIDTH // 2], chunk[WIDTH // 2 :])
        shown = "  ".join(" ".join(f"{b:02X}" for b in half) for half in halves if half)
        return f"{self.address + row * WIDTH:08X}", shown, text_of(chunk)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            if index.column() == FILE:
                return self.file_row(index.row())
            return self.row(index.row())[index.column()]
        return None


class MemoryView(QWidget):
    #: Read... was pressed: somebody else asks what to read and reads it.
    read_requested = Signal()

    def __init__(self, flasher: Flasher, ctx: Context) -> None:
        super().__init__()
        self.flasher = flasher
        self.ctx = ctx
        #: What the read was of, for the summary and for a file's name.
        self.target = ""
        #: Whether what is shown is anywhere but here. True from the
        #: moment something is read until it has been saved.
        self.unsaved = False

        self.summary = QLabel(NOTHING)
        self.summary.setWordWrap(True)

        self.model = MemoryModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setFont(fonts.mono())
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        # Close together, as lines of a dump are read: a table's own spacing
        # shows half as many, and these are read a screenful at a time.
        self.table.verticalHeader().setDefaultSectionSize(fonts.text_height() + 6)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAccessibleName("Memory read from the target")
        header = self.table.horizontalHeader()
        # Sized once from a full row, not from the contents: asking a
        # million rows how wide they are is asking a million rows.
        header.setSectionResizeMode(QHeaderView.Fixed)
        for column, sample in (
            (ADDRESS, "00000000"),
            (BYTES, "00 " * WIDTH + " "),
            (TEXT, "M" * WIDTH + " "),
            (FILE, "00 " * WIDTH + " "),
        ):
            self.table.setColumnWidth(column, fonts.width_for(self.table, sample))
        header.setStretchLastSection(True)
        # There only while there is a comparison for it to show, and then
        # beside the bytes it is to be read against rather than past the text.
        header.moveSection(FILE, TEXT)
        self.table.setColumnHidden(FILE, True)

        self.goto = QLineEdit()
        self.goto.setFont(fonts.mono())
        self.goto.setAccessibleName("Go to address")
        self.goto.setToolTip(GOTO_TIP)
        self.goto.setMaximumWidth(fonts.width_for(self.goto, "00000000") + 24)
        self.goto.returnPressed.connect(self.go_to)
        self.find_as = QComboBox()
        self.find_as.addItems([AS_BYTES, AS_TEXT])
        self.find_as.setAccessibleName("Find bytes or text")
        self.find = QLineEdit()
        self.find.setAccessibleName("Find")
        self.find.setToolTip(FIND_TIP)
        self.find.returnPressed.connect(self.find_next)
        self.previous_button = QPushButton("Previous")
        self.previous_button.setToolTip("Find the one before. Shift+F3.")
        self.previous_button.clicked.connect(self.find_previous)
        self.next_button = QPushButton("Next")
        self.next_button.setToolTip("Find the next. F3.")
        self.next_button.clicked.connect(self.find_next)
        #: What going to an address or finding something came to, in
        #: words: the row is selected as well, but a row does not say
        #: which of its sixteen bytes was meant.
        self.found = QLabel()
        #: Where the last thing found starts, as an offset into what was
        #: read, for the next search to carry on from. None before any.
        self._found_at: int | None = None
        #: What that was a search for. Something else looked for starts from
        #: the top, and is not the next of what was looked for before.
        self._looked_for = b""
        for keys, slot in (
            (QKeySequence.Find, self._focus_find),
            (QKeySequence("Ctrl+G"), self._focus_goto),
            (QKeySequence.FindNext, self.find_next),
            (QKeySequence.FindPrevious, self.find_previous),
        ):
            shortcut = QShortcut(keys, self)
            # In this pane and not the whole window: Ctrl+F means this
            # only while it is this that is being looked at.
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

        looking = QHBoxLayout()
        looking.addWidget(QLabel("Go to:"))
        looking.addWidget(self.goto)
        looking.addWidget(QLabel("Find:"))
        looking.addWidget(self.find_as)
        looking.addWidget(self.find, 1)
        looking.addWidget(self.previous_button)
        looking.addWidget(self.next_button)

        self.read_button = QPushButton("Read...")
        self.read_button.setToolTip(
            "Read part of the connected target's memory, changing nothing in the target."
        )
        self.read_button.clicked.connect(self.read_requested.emit)
        self.save_button = QPushButton("Save...")
        self.save_button.setToolTip(
            "Save what is shown here in a file: raw binary, Intel HEX or S-record."
        )
        self.save_button.clicked.connect(self.save)
        self.compare_button = QPushButton("Compare...")
        self.compare_button.setToolTip(
            "Compare what is shown here with a firmware file, and mark where\n"
            "they differ. Nothing is read from the target."
        )
        self.compare_button.clicked.connect(self.compare_with_file)
        #: What comparing found, in words.
        self.compared = QLabel()
        self.compared.setWordWrap(True)
        self.previous_difference = QPushButton("Previous difference")
        self.previous_difference.clicked.connect(lambda: self._to_difference(False))
        self.next_difference = QPushButton("Next difference")
        self.next_difference.clicked.connect(lambda: self._to_difference(True))
        #: Where the difference last gone to starts, as an offset.
        self._difference_at: int | None = None
        differences = QHBoxLayout()
        differences.addWidget(self.compared, 1)
        differences.addWidget(self.previous_difference)
        differences.addWidget(self.next_difference)

        self.trim = QCheckBox("Leave off the erased bytes at the end")
        self.trim.setToolTip(TRIM_TIP)

        buttons = QHBoxLayout()
        buttons.addWidget(self.read_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.compare_button)
        buttons.addWidget(self.trim)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(looking)
        layout.addWidget(self.found)
        layout.addLayout(differences)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

        # To methods and not to lambdas: a pane of these is thrown away
        # when it is closed, and Qt lets go of a method of an object that
        # has gone where it would go on calling a lambda that held one.
        flasher.connection_changed.connect(self._on_flasher)
        flasher.busy_changed.connect(self._on_flasher)
        self._show_comparison(None)
        self._enable()

    def title(self) -> str:
        """What the read is of, for the pane's title: where, and how much.

        Not the target as well. A tab shows the start of a title and no
        more, and several panes that all began with the same name would
        be several tabs the same; the line inside says which target.
        """
        return f"{self.model.address:08X}, {size_text(len(self.model.data_read))}"

    def show_memory(self, address: int, data: bytes, target: str) -> None:
        """Show what has just been read, in place of what was read before."""
        self.target = target
        self.unsaved = True
        self.model.show(address, data)
        self.table.scrollToTop()
        # What was found was found in what was read before.
        self._found_at = None
        self.found.setText("")
        # And what it was compared with was compared with that.
        self._show_comparison(None)
        self.summary.setText(
            f"{target}: {size_text(len(data))} from {address:08X} to "
            f"{address + len(data) - 1:08X}, read at {datetime.now():%H:%M:%S}."
        )
        self._enable()

    def _on_flasher(self, _state: bool) -> None:
        self._enable()

    def _enable(self) -> None:
        self.read_button.setEnabled(self.flasher.connected and not self.flasher.busy)
        anything = bool(self.model.data_read)
        for widget in (
            self.save_button,
            self.compare_button,
            self.goto,
            self.find_as,
            self.find,
            self.previous_button,
            self.next_button,
        ):
            widget.setEnabled(anything)

    # --- looking for something -------------------------------------------------------
    def _focus_find(self) -> None:
        self.find.setFocus()
        self.find.selectAll()

    def _focus_goto(self) -> None:
        self.goto.setFocus()
        self.goto.selectAll()

    def _show_offset(self, offset: int) -> None:
        """Bring the row this byte is on into view, and select it."""
        row = offset // WIDTH
        self.table.selectRow(row)
        self.table.scrollTo(self.model.index(row, 0), QAbstractItemView.PositionAtCenter)

    def go_to(self) -> None:
        """Go to the address typed, if it is one that was read."""
        data, start = self.model.data_read, self.model.address
        if not data:
            return
        typed = self.goto.text().strip()
        address = parse_address(typed)
        if address is None:
            self.found.setText(f"{typed!r} is not an address: it wants hexadecimal.")
        elif not start <= address < start + len(data):
            self.found.setText(
                f"{address:08X} is not in what was read, which is {start:08X} to "
                f"{start + len(data) - 1:08X}."
            )
        else:
            self._show_offset(address - start)
            self.found.setText(f"At {address:08X}.")

    def _wanted(self) -> bytes | None:
        """The bytes Find is to look for; None, having said why, if there are none."""
        typed = self.find.text()
        if not typed:
            self.found.setText("")
            return None
        if self.find_as.currentText() == AS_TEXT:
            # As the Text column shows them: one byte to a character.
            return typed.encode("latin-1", "replace")
        wanted = parse_bytes(typed)
        if wanted is None:
            self.found.setText(
                f"{typed!r} is not bytes in hexadecimal: two digits to a byte, such as "
                "DE AD BE EF. To look for the letters themselves, choose Text."
            )
        return wanted

    def _find(self, forwards: bool) -> None:
        data = self.model.data_read
        if not data or (wanted := self._wanted()) is None:
            return
        if wanted != self._looked_for:
            self._looked_for, self._found_at = wanted, None
        last = self._found_at
        if forwards:
            at = data.find(wanted, 0 if last is None else last + 1)
            wrapped = at < 0
            if wrapped:
                at = data.find(wanted)
        else:
            # rfind's end is where a match may not reach past, so one
            # that starts before the last found ends before this.
            at = -1 if last is None else data.rfind(wanted, 0, last + len(wanted) - 1)
            wrapped = at < 0
            if wrapped:
                at = data.rfind(wanted)
        if at < 0:
            self._found_at = None
            self.found.setText("Not found in what was read.")
            return
        # Said only when there was somewhere to go round from: the first
        # search of all starts at the start and goes round nothing.
        went_round = wrapped and last is not None
        self._found_at = at
        self._show_offset(at)
        where = f"Found at {self.model.address + at:08X}"
        if went_round:
            where += ", having gone round from the " + ("end" if forwards else "start")
        self.found.setText(where + ".")

    def find_next(self) -> None:
        self._find(forwards=True)

    def find_previous(self) -> None:
        self._find(forwards=False)

    # --- comparing with a file -------------------------------------------------------
    def _show_comparison(self, made: Comparison | None) -> None:
        self.model.show_comparison(made)
        self._difference_at = None
        self.table.setColumnHidden(FILE, made is None)
        if made is not None:
            self._make_room()
        differs = made is not None and made.different > 0
        for button in (self.previous_difference, self.next_difference):
            button.setVisible(made is not None)
            button.setEnabled(differs)
        self.compared.setVisible(made is not None)
        self.compared.setText(comparison_text(made) if made is not None else "")

    def _make_room(self) -> None:
        """Widen a window of the pane's own until every column can be seen.

        The File column is as wide again as the bytes. In the main window the
        room is the user's to arrange; a window that holds only this pane is
        the pane's to size, and one that hid half of what was asked for would
        be sized wrongly.
        """
        top = self.window()
        if top is None or top.inherits("QMainWindow"):
            return
        header = self.table.horizontalHeader()
        columns = sum(
            self.table.columnWidth(c) for c in range(len(HEADINGS)) if not header.isSectionHidden(c)
        )
        wanted = columns + self.table.verticalScrollBar().sizeHint().width() + 48
        if top.width() < wanted:
            top.resize(wanted, top.height())

    def compare_with_file(self) -> None:
        """Ask for a file, and mark where what is shown differs from it."""
        if not self.model.data_read:
            return
        path = folders.open_file(
            self,
            self.ctx,
            folders.IMAGE,
            "Compare with a firmware file",
            images.READ_FILTER,
            Path.home(),
        )
        if path:
            self.compare_with(path)

    def compare_with(self, path: str) -> None:
        try:
            # A raw binary has no addresses of its own, so it is taken to
            # start where what was read starts: that is what it would be
            # a copy of.
            image = images.read(path, address=self.model.address)
        except ImageError as exc:
            self.ctx.events.error(f"{Path(path).name} cannot be read: {exc}")
            return
        made = compare(self.model.address, self.model.data_read, image)
        self._show_comparison(made)
        said = comparison_text(made)
        if made.compared == 0:
            self.ctx.events.warning(said)
        elif made.different:
            self.ctx.events.error(said)
            self._to_difference(True)
        else:
            self.ctx.events.good(said)

    def _to_difference(self, forwards: bool) -> None:
        """Go to the next stretch of bytes that differ, or the one before."""
        made = self.model.comparison
        if made is None:
            return
        at = (
            made.next_run(self._difference_at)
            if forwards
            else made.previous_run(self._difference_at)
        )
        if at is None:
            return
        self._difference_at = at
        self._show_offset(at)
        self.found.setText(difference_text(made, self.model.data_read, at))

    def to_save(self) -> bytes:
        """What is shown, less the erased bytes at the end if that is ticked."""
        data = self.model.data_read
        return data.rstrip(b"\xff") if self.trim.isChecked() else data

    def save(self) -> bool:
        """Ask where, and save what is shown there. Whether it was saved."""
        data = self.to_save()
        if not data:
            self.ctx.events.warning(
                "All of what was read is erased, so there is nothing to save. "
                "Untick the box to save it as it is."
            )
            return False
        address = self.model.address
        path = folders.save_file(
            self,
            self.ctx,
            folders.EXPORT,
            "Save what was read",
            images.WRITE_FILTER,
            Path.home(),
            # The time in the name: a read is saved to be kept, and the
            # next one must not offer to overwrite it.
            suggested=folders.stamped(f"{self.target}_{address:08X}", ".bin"),
        )
        if not path:
            return False
        try:
            fmt = images.write(path, address, data)
        except ImageError as exc:
            self.ctx.events.error(f"Saving to {path} failed: {exc}")
            return False
        self.unsaved = False
        self.ctx.events.good(
            f"Saved {size_text(len(data))} from {address:08X} of {self.target} as {fmt} in {path}."
        )
        return True


def may_close(view: MemoryView) -> bool:
    """Whether a Memory pane may be closed: asked, if what is in it is not saved.

    What was read is only in the pane until it is saved, so closing one that
    has not been says so first. It can then be saved, thrown away, or kept
    open; and a Save that was cancelled, or failed, has saved nothing, and
    keeps it open too.
    """
    if not view.unsaved:
        return True
    answer = messages.warning(
        view,
        "Close without saving?",
        f"What was read from {view.target} is only in this pane. Closing it without saving "
        "throws it away.",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        QMessageBox.Cancel,
    )
    if answer == QMessageBox.Save:
        return view.save()
    return answer == QMessageBox.Discard
