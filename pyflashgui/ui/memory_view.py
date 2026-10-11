# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Memory pane: what was last read from a target, to look at and to save.

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
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core import images
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher, size_text
from pyflashgui.core.images import ImageError
from pyflashgui.ui import folders, fonts
from pyflashgui.ui.files_view import parse_address

#: Bytes shown on a row.
WIDTH = 16
ADDRESS, BYTES, TEXT = range(3)
HEADINGS = ("Address", "Bytes", "Text")

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


def text_of(data: bytes) -> str:
    """The characters these bytes spell, with a dot for each that spells none."""
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


class MemoryModel(QAbstractTableModel):
    """Sixteen bytes a row: where they are, what they are, and what they spell."""

    def __init__(self) -> None:
        super().__init__()
        self.address = 0
        self.data_read = b""

    def show(self, address: int, data: bytes) -> None:
        self.beginResetModel()
        self.address, self.data_read = address, data
        self.endResetModel()

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
            (TEXT, "M" * WIDTH),
        ):
            self.table.setColumnWidth(column, fonts.width_for(self.table, sample))
        header.setStretchLastSection(True)

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
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

        flasher.connection_changed.connect(lambda _on: self._enable())
        flasher.busy_changed.connect(lambda _busy: self._enable())
        self._enable()

    def show_memory(self, address: int, data: bytes, target: str) -> None:
        """Show what has just been read, in place of what was read before."""
        self.target = target
        self.model.show(address, data)
        self.table.scrollToTop()
        # What was found was found in what was read before.
        self._found_at = None
        self.found.setText("")
        self.summary.setText(
            f"{target}: {size_text(len(data))} from {address:08X} to "
            f"{address + len(data) - 1:08X}, read at {datetime.now():%H:%M:%S}."
        )
        self._enable()

    def _enable(self) -> None:
        self.read_button.setEnabled(self.flasher.connected and not self.flasher.busy)
        anything = bool(self.model.data_read)
        for widget in (
            self.save_button,
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

    def to_save(self) -> bytes:
        """What is shown, less the erased bytes at the end if that is ticked."""
        data = self.model.data_read
        return data.rstrip(b"\xff") if self.trim.isChecked() else data

    def save(self) -> None:
        data = self.to_save()
        if not data:
            self.ctx.events.warning(
                "All of what was read is erased, so there is nothing to save. "
                "Untick the box to save it as it is."
            )
            return
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
            return
        try:
            fmt = images.write(path, address, data)
        except ImageError as exc:
            self.ctx.events.error(f"Saving to {path} failed: {exc}")
            return
        self.ctx.events.good(
            f"Saved {size_text(len(data))} from {address:08X} of {self.target} as {fmt} in {path}."
        )
