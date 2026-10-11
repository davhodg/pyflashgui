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
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
        self.summary.setText(
            f"{target}: {size_text(len(data))} from {address:08X} to "
            f"{address + len(data) - 1:08X}, read at {datetime.now():%H:%M:%S}."
        )
        self._enable()

    def _enable(self) -> None:
        self.read_button.setEnabled(self.flasher.connected and not self.flasher.busy)
        self.save_button.setEnabled(bool(self.model.data_read))

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
