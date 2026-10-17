# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A Memory pane: the bytes of one entry in the Files list, to look at and to save.

What a file holds and what was read from a target are shown the same way, as
addresses, bytes and the characters they spell. A read goes into memory and
is shown here; saving it is a second step, taken when it has been looked at
and found worth keeping: most reads are to see what is there, and a file for
each would be a folder of files nobody opens again.

A file can be in several pieces with nothing between them. Each piece starts
a row of its own at its own address, and the rows of one follow the rows of
the one before: the gaps are not shown, since there is nothing in them.

The rows are worked out as they are drawn. A whole flash is a million of
them, and making each one in advance would take longer than reading it did.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from datetime import datetime

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
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core import images
from pyflashgui.core.compare import DIFFERENT, Comparison, compare_all
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher, size_text
from pyflashgui.core.images import Image, Segment
from pyflashgui.core.memory_map import region_at
from pyflashgui.ui import fonts
from pyflashgui.ui.files_view import Entry, parse_address, save_entry

#: Bytes shown on a row.
WIDTH = 16
ADDRESS, BYTES, TEXT, FILE = range(4)
HEADINGS = ("Address", "Bytes", "Text", "Compared with")

#: In the File column, a byte the file agrees about and one it says
#: nothing about. What is left to read is what differs.
AGREES, UNMENTIONED = "..", "--"
#: How many bytes of a difference are spelled out in the line about it.
MOST_SHOWN = 8

NOTHING = "Nothing is shown yet. Read... reads part of the connected target's memory."
TRIM_TIP = (
    "Erased flash reads as FF on most devices, and as 00 on some. With this\n"
    "ticked, the erased bytes after the last byte that holds something are\n"
    "not saved, so the file is the size of what is there and not the size of\n"
    "what was read. The target's own erased value is used where it is known."
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


def comparison_text(made: Comparison, address_of: Callable[[int], int] | None = None) -> str:
    """What comparing found, in a sentence or two.

    ``address_of`` says where a byte of what was compared is, for what is
    in more pieces than one. Without it, they follow from where it starts.
    """
    if made.compared == 0:
        return (
            f"Compared with {made.name}: none of it is at the addresses shown here, "
            "so there was nothing to compare."
        )
    if made.different:
        first = address_of(made.first) if address_of else made.address + made.first
        count = "1 byte differs" if made.different == 1 else f"{made.different} bytes differ"
        said = (
            f"Compared with {made.name}: {count} of {size_text(made.compared)}, the first "
            f"at {first:08X}."
        )
    else:
        said = f"Compared with {made.name}: {size_text(made.compared)} compared, all the same."
    # What each has that the other does not is said, and is not a
    # difference: neither is wrong about what it does not mention.
    if made.outside:
        said += f" {size_text(made.outside)} of {made.name} are outside what is shown here."
    if made.unmentioned:
        said += f" {size_text(made.unmentioned)} of what is shown here are not in {made.name}."
    return said


def difference_text(
    made: Comparison, data: bytes, at: int, address_of: Callable[[int], int] | None = None
) -> str:
    """One stretch of differing bytes: where, how long, and both sides of it."""
    length = made.run_from(at)
    shown = min(length, MOST_SHOWN)
    more = " ..." if length > shown else ""
    theirs = " ".join(f"{b:02X}" for b in made.file[at : at + shown])
    ours = " ".join(f"{b:02X}" for b in data[at : at + shown])
    size = "1 byte" if length == 1 else f"{length} bytes"
    where = address_of(at) if address_of else made.address + at
    return (
        f"Differs at {where:08X} for {size}: here it is {ours}{more}, "
        f"in {made.name} {theirs}{more}."
    )


def text_of(data: bytes) -> str:
    """The characters these bytes spell, with a dot for each that spells none."""
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


class MemoryModel(QAbstractTableModel):
    """Sixteen bytes a row: where they are, what they are, and what they spell."""

    def __init__(self) -> None:
        super().__init__()
        #: The pieces shown, in the order they are shown in.
        self.segments: tuple[Segment, ...] = ()
        #: All of them end to end. An offset into this is how a byte is
        #: named everywhere here: finding, comparing and going to one.
        self.data_read = b""
        #: For each piece, the offset it starts at and the row it starts on.
        self._starts: list[int] = []
        self._first_rows: list[int] = []
        self._rows = 0
        #: What it was last compared with, if anything since it was shown.
        self.comparison: Comparison | None = None

    @property
    def address(self) -> int:
        """Where the first piece starts."""
        return self.segments[0].address if self.segments else 0

    def show(self, address: int, data: bytes) -> None:
        self.show_segments((Segment(address, data),))

    def show_segments(self, segments: Sequence[Segment]) -> None:
        self.beginResetModel()
        self.segments = tuple(segments)
        # One piece is shown as it is: a whole flash is not copied to be looked at.
        self.data_read = (
            self.segments[0].data
            if len(self.segments) == 1
            else b"".join(s.data for s in self.segments)
        )
        self._starts, self._first_rows = [], []
        at = rows = 0
        for segment in self.segments:
            self._starts.append(at)
            self._first_rows.append(rows)
            at += len(segment)
            rows += -(-len(segment) // WIDTH)
        self._rows = rows
        # A comparison is of what was shown, and this is something else.
        self.comparison = None
        self.endResetModel()

    def _piece(self, offset: int) -> int:
        """Which piece the byte at this offset is in."""
        return max(0, bisect_right(self._starts, offset) - 1)

    def span(self, row: int) -> tuple[int, int, int]:
        """A row's address, and the offsets its bytes run from and to."""
        piece = max(0, bisect_right(self._first_rows, row) - 1)
        segment = self.segments[piece]
        within = (row - self._first_rows[piece]) * WIDTH
        start = self._starts[piece] + within
        return (
            segment.address + within,
            start,
            min(start + WIDTH, self._starts[piece] + len(segment)),
        )

    def row_of(self, offset: int) -> int:
        piece = self._piece(offset)
        return self._first_rows[piece] + (offset - self._starts[piece]) // WIDTH

    def address_of(self, offset: int) -> int:
        piece = self._piece(offset)
        return self.segments[piece].address + offset - self._starts[piece]

    def offset_of(self, address: int) -> int | None:
        """The offset of the byte at this address, or None if no piece has it."""
        for segment, start in zip(self.segments, self._starts, strict=True):
            if segment.address <= address < segment.end:
                return start + address - segment.address
        return None

    def crosses(self, offset: int, length: int) -> bool:
        """Whether this many bytes from here run out of one piece into the next.

        Those are side by side here and not in the memory they came from.
        """
        piece = self._piece(offset)
        return offset + length > self._starts[piece] + len(self.segments[piece])

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
        if made is None:
            return ""
        _address, start, stop = self.span(row)
        if DIFFERENT not in made.differs[start:stop]:
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
        return 0 if parent.isValid() else self._rows

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADINGS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section == FILE and self.comparison is not None:
                return self.comparison.name  # whose bytes that column has
            return HEADINGS[section]
        return None

    def row(self, row: int) -> tuple[str, str, str]:
        """One row as it is shown: its address, its bytes and their text."""
        address, start, stop = self.span(row)
        chunk = self.data_read[start:stop]
        # A gap after the eighth, so that a byte can be found by eye.
        halves = (chunk[: WIDTH // 2], chunk[WIDTH // 2 :])
        shown = "  ".join(" ".join(f"{b:02X}" for b in half) for half in halves if half)
        return f"{address:08X}", shown, text_of(chunk)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            if index.column() == FILE:
                return self.file_row(index.row())
            return self.row(index.row())[index.column()]
        return None


class MemoryView(QWidget):
    #: Read... was pressed: somebody else asks what to read and reads it.
    read_requested = Signal()
    #: What is shown has been saved: the list it is on says so no longer.
    saved = Signal()

    def __init__(self, flasher: Flasher, ctx: Context) -> None:
        super().__init__()
        self.flasher = flasher
        self.ctx = ctx
        #: The entry of the Files list whose bytes these are. None until
        #: there is one.
        self.entry: Entry | None = None
        #: What it holds as it was last shown, to tell when that has changed.
        self._shown: Image | None = None
        #: What it is of, to say so: the target of a read, a file's name.
        self.target = ""

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
        self.table.setAccessibleName("The bytes of a file or a read")
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
            "Save what is shown here in a file: raw binary, Intel HEX or S-record.\n"
            "For what is in one piece, as everything read from a target is."
        )
        self.save_button.clicked.connect(self.save)
        #: What comparing found, in words. Compare, in the Files pane, is
        #: what compares: this with another entry of that list.
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

    @property
    def unsaved(self) -> bool:
        """Whether what is shown is a read that is nowhere but in memory."""
        return self.entry is not None and self.entry.unsaved

    @unsaved.setter
    def unsaved(self, unsaved: bool) -> None:
        if self.entry is not None:
            self.entry.unsaved = unsaved

    def title(self) -> str:
        """What is shown, for the pane's title: its name in the Files list."""
        return self.entry.name if self.entry is not None else ""

    def show_memory(self, address: int, data: bytes, target: str) -> None:
        """Show these bytes as what has just been read from a target."""
        self.show_entry(
            Entry(
                path="Read",
                enabled=False,
                image=Image("Read", images.BINARY, (Segment(address, data),)),
                target=target,
                when=f"{datetime.now():%H:%M:%S}",
                unsaved=True,
            )
        )

    def show_entry(self, entry: Entry) -> None:
        """Show what this entry of the Files list holds, in place of what was shown."""
        self.entry = entry
        self.target = entry.target or entry.name
        self._show(entry.image)
        self.table.scrollToTop()

    def refresh(self) -> None:
        """Show the entry again if what it holds has changed: a build wrote its file."""
        if self.entry is None or self.entry.image is self._shown:
            return
        bar = self.table.verticalScrollBar()
        at = bar.value()
        self._show(self.entry.image)
        bar.setValue(at)

    def _show(self, image: Image | None) -> None:
        self._shown = image
        self.model.show_segments(image.segments if image is not None else ())
        # What was found was found in what was shown before.
        self._found_at = None
        self.found.setText("")
        # And what it was compared with was compared with that.
        self._show_comparison(None)
        self.summary.setText(self._summary())
        self._enable()

    def _summary(self) -> str:
        entry, pieces = self.entry, self.model.segments
        if entry is None:
            return NOTHING
        if entry.image is None:
            return f"{entry.name} cannot be read: {entry.problem}"
        if not pieces:
            return f"{entry.name} holds nothing."
        size = size_text(len(self.model.data_read))
        span = f"from {pieces[0].address:08X} to {max(s.end for s in pieces) - 1:08X}"
        if entry.is_read:
            return f"{entry.target}: {size} {span}, read at {entry.when}."
        said = f"{entry.name}: {entry.image.format}, {size} {span}"
        return said + (f", in {len(pieces)} pieces." if len(pieces) > 1 else ".")

    def _on_flasher(self, _state: bool) -> None:
        self._enable()

    def _enable(self) -> None:
        self.read_button.setEnabled(self.flasher.connected and not self.flasher.busy)
        anything = bool(self.model.data_read)
        self.save_button.setEnabled(anything and len(self.model.segments) == 1)
        for widget in (
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
        row = self.model.row_of(offset)
        self.table.selectRow(row)
        self.table.scrollTo(self.model.index(row, 0), QAbstractItemView.PositionAtCenter)

    def go_to(self) -> None:
        """Go to the address typed, if it is one that is shown."""
        data, pieces = self.model.data_read, self.model.segments
        if not data:
            return
        typed = self.goto.text().strip()
        address = parse_address(typed)
        if address is None:
            self.found.setText(f"{typed!r} is not an address: it wants hexadecimal.")
        elif (offset := self.model.offset_of(address)) is None:
            start, end = pieces[0].address, max(s.end for s in pieces) - 1
            self.found.setText(
                f"{address:08X} is not in what was read, which is {start:08X} to {end:08X}."
                if len(pieces) == 1
                else f"{address:08X} is in none of the {len(pieces)} pieces shown, which are "
                f"between {start:08X} and {end:08X}."
            )
        else:
            self._show_offset(offset)
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

    def _next(self, wanted: bytes, start: int) -> int:
        """Where these bytes are next, at or after ``start``, within one piece. -1 if nowhere."""
        data = self.model.data_read
        at = data.find(wanted, start)
        while at >= 0 and self.model.crosses(at, len(wanted)):
            at = data.find(wanted, at + 1)
        return at

    def _before(self, wanted: bytes, end: int) -> int:
        """Where they last are, ending at or before ``end``, within one piece."""
        data = self.model.data_read
        at = data.rfind(wanted, 0, end)
        while at >= 0 and self.model.crosses(at, len(wanted)):
            at = data.rfind(wanted, 0, at + len(wanted) - 1)
        return at

    def _find(self, forwards: bool) -> None:
        data = self.model.data_read
        if not data or (wanted := self._wanted()) is None:
            return
        if wanted != self._looked_for:
            self._looked_for, self._found_at = wanted, None
        last = self._found_at
        if forwards:
            at = self._next(wanted, 0 if last is None else last + 1)
            wrapped = at < 0
            if wrapped:
                at = self._next(wanted, 0)
        else:
            # The end is where a match may not reach past, so one that
            # starts before the last found ends before this.
            at = -1 if last is None else self._before(wanted, last + len(wanted) - 1)
            wrapped = at < 0
            if wrapped:
                at = self._before(wanted, len(data))
        if at < 0:
            self._found_at = None
            self.found.setText("Not found in what was read.")
            return
        # Said only when there was somewhere to go round from: the first
        # search of all starts at the start and goes round nothing.
        went_round = wrapped and last is not None
        self._found_at = at
        self._show_offset(at)
        where = f"Found at {self.model.address_of(at):08X}"
        if went_round:
            where += ", having gone round from the " + ("end" if forwards else "start")
        self.found.setText(where + ".")

    def find_next(self) -> None:
        self._find(forwards=True)

    def find_previous(self) -> None:
        self._find(forwards=False)

    # --- comparing with another ------------------------------------------------------
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
        self.compared.setText(
            comparison_text(made, self.model.address_of) if made is not None else ""
        )

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

    def compare_with(self, image: Image, quiet: bool = False) -> None:
        """Mark where what is shown differs from another file or read.

        ``quiet`` leaves the Event Log out of it: for the other half of a
        comparison already said there.
        """
        if not self.model.data_read:
            return
        made = compare_all(self.model.segments, image)
        self._show_comparison(made)
        if quiet:
            if made.different:
                self._to_difference(True)
            return
        found = comparison_text(made, self.model.address_of)
        # The line in the pane starts "Compared with ...", which in the log,
        # away from the pane, does not say what was compared with it.
        found = found.split(": ", 1)[1] if found.startswith("Compared with ") else found
        said = f"Comparison result for {self.title()} against {made.name}: {found}"
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
        self.found.setText(difference_text(made, self.model.data_read, at, self.model.address_of))

    def to_save(self) -> bytes:
        """What is shown, less the erased bytes at the end if that is ticked."""
        data = self.model.data_read
        return data.rstrip(bytes([self._erased()])) if self.trim.isChecked() else data

    def _erased(self) -> int:
        """What the flash this was read from reads as erased: FF unless the
        target says otherwise, as an XMC4500's 00 does."""
        if self.model.segments:
            region = region_at(self.flasher.regions, self.model.segments[0].address)
            if region is not None:
                return region.erased
        return 0xFF

    def save(self) -> bool:
        """Ask where, and save what is shown there. Whether it was saved."""
        if self.entry is None or len(self.model.segments) != 1:
            return False
        data = self.to_save()
        if not data:
            self.ctx.events.warning(
                "All of what was read is erased, so there is nothing to save. "
                "Untick the box to save it as it is."
            )
            return False
        if not save_entry(self, self.ctx, self.entry, data):
            return False
        self.saved.emit()
        return True
