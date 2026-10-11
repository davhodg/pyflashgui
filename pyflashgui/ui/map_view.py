# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Memory Map pane: what the ticked files will write, and where.

Three things, top to bottom: what is wrong, how much of each flash region the
files take up, and every piece of every file with the region it lands in.
What is wrong comes first, because it is the reason to look.

It shows what ``core/memory_map.py`` worked out and decides nothing itself,
so what is on screen and what Program checks before it starts cannot differ.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core.events import ERROR
from pyflashgui.core.flasher import size_text
from pyflashgui.core.images import Image
from pyflashgui.core.memory_map import Layout, Region, lay_out
from pyflashgui.ui import event_colours, fonts

HEADINGS = ("File", "From", "To", "Size", "Region")

NOTHING = "No file is ticked, so there is nothing to place."
UNCHECKED = (
    "The memory of this target is not known until it is connected to, so the "
    "files have not been checked against it."
)
NO_TARGET = "No target is chosen, so the files have not been checked against one."
FITS = "Everything fits."

#: The word a problem begins with. The line is coloured as well, but a colour
#: is no use to somebody who cannot tell red from amber.
WORDS = {ERROR: "Error"}
OTHER_WORD = "Warning"
#: How many problems are spelled out before the rest are counted. A file
#: built for another part can be wrong in every one of its pieces, and
#: forty lines saying so would push everything else out of the pane.
MOST_PROBLEMS = 8


def _discard(layout: QLayout, widget: QWidget) -> None:
    """Take a widget out of a layout and off the screen, for good.

    Hidden and orphaned as well as deleted later: a widget waiting to be
    deleted is still drawn where it last was until it is, over whatever
    has taken its place.
    """
    layout.removeWidget(widget)
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def usage_text(used: int, length: int, sectors: int, erased: int) -> str:
    filled = f"{size_text(used)} of {size_text(length)} ({100 * used / length:.1f} %)"
    if not sectors:
        # Where the size of a sector is not known, what is erased is not
        # either, and is not guessed at.
        return filled
    sector_text = "1 sector" if sectors == 1 else f"{sectors} sectors"
    return f"{filled}, erasing {sector_text}, {size_text(erased)}"


class MapView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.layout_shown: Layout | None = None

        self.summary = QLabel()
        self.summary.setWordWrap(True)

        #: What is wrong, a line each. Empty, and so taking no room, when
        #: nothing is.
        self.problems = QVBoxLayout()
        self.problem_labels: list[QLabel] = []

        #: A row per flash region something is written to: its name, a bar
        #: and the figures the bar stands for.
        self.usage = QGridLayout()
        self.usage.setColumnStretch(1, 1)
        self._usage_widgets: list[QWidget] = []

        self.pieces = QTableWidget(0, len(HEADINGS))
        self.pieces.setHorizontalHeaderLabels(HEADINGS)
        self.pieces.verticalHeader().setVisible(False)
        self.pieces.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pieces.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pieces.setAccessibleName("Where each piece of each file lands")
        header = self.pieces.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(self.problems)
        layout.addLayout(self.usage)
        layout.addWidget(self.pieces, 1)
        self.show_layout([], [], "")

    def show_layout(
        self,
        files: Sequence[Image],
        regions: Sequence[Region],
        target: str,
        complete: bool = True,
    ) -> None:
        """Lay these files over this memory and show what comes of it."""
        made = lay_out(files, regions, complete)
        self.layout_shown = made
        self._show_summary(made, bool(files), target)
        self._show_problems(made)
        self._show_usage(made)
        self._show_pieces(made)

    def _show_summary(self, made: Layout, any_files: bool, target: str) -> None:
        if not any_files:
            text = NOTHING
        elif not made.checked:
            text = UNCHECKED if target else NO_TARGET
        elif made.problems:
            errors = sum(p.level == ERROR for p in made.problems)
            warnings = len(made.problems) - errors
            counts = []
            if errors:
                counts.append("1 error" if errors == 1 else f"{errors} errors")
            if warnings:
                counts.append("1 warning" if warnings == 1 else f"{warnings} warnings")
            text = f"{target}: {' and '.join(counts)}."
            if errors:
                text += " These files cannot be programmed as they are."
        else:
            text = f"{target}: {FITS}"
        self.summary.setText(text)

    def _show_problems(self, made: Layout) -> None:
        for label in self.problem_labels:
            _discard(self.problems, label)
        self.problem_labels = []
        dark = event_colours.dark_behind(self.palette())
        # Errors first: they are what stops Program, and a warning above
        # them would be read as the thing to put right.
        ordered = sorted(made.problems, key=lambda p: p.level != ERROR)
        shown = ordered[:MOST_PROBLEMS]
        lines = [(p.level, f"{WORDS.get(p.level, OTHER_WORD)}: {p.message}") for p in shown]
        if len(ordered) > len(shown):
            lines.append((ordered[len(shown)].level, f"And {len(ordered) - len(shown)} more."))
        for level, text in lines:
            # A label a line, wrapped: each takes the height it needs, where
            # a list would have to be told and would cut a long one short.
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if (colour := event_colours.colour_for(level, dark)) is not None:
                palette = label.palette()
                palette.setColor(QPalette.WindowText, colour)
                label.setPalette(palette)
            self.problems.addWidget(label)
            self.problem_labels.append(label)

    def _show_usage(self, made: Layout) -> None:
        for widget in self._usage_widgets:
            _discard(self.usage, widget)
        self._usage_widgets = []
        for row, usage in enumerate(made.usage):
            name = QLabel(usage.region.name)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(usage.fraction * 1000))
            bar.setTextVisible(False)
            bar.setAccessibleName(f"How full {usage.region.name} is")
            figures = QLabel(
                usage_text(usage.used, usage.region.length, usage.sectors, usage.erased)
            )
            for column, widget in enumerate((name, bar, figures)):
                self.usage.addWidget(widget, row, column)
                self._usage_widgets.append(widget)

    def _show_pieces(self, made: Layout) -> None:
        self.pieces.setRowCount(len(made.pieces))
        mono = fonts.mono()
        for row, piece in enumerate(sorted(made.pieces, key=lambda p: (p.address, p.source))):
            if piece.region is not None:
                where = piece.region.name
            else:
                where = "Outside the target's memory" if made.checked else ""
            cells = (
                piece.source,
                f"{piece.address:08X}",
                f"{piece.end - 1:08X}",
                size_text(piece.length),
                where,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column in (1, 2):
                    item.setFont(mono)
                self.pieces.setItem(row, column, item)
