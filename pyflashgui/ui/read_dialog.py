# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Which part of a target's memory to read back.

Asked before the file is, because what is read decides what the file should
be called. A region of the target fills in the address and the length, and
both can still be typed over: what is wanted is as often the first few
kilobytes of a region as the whole of it.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core.flasher import size_text
from pyflashgui.core.memory_map import FLASH, Region
from pyflashgui.ui import fonts

OTHER = "Another range"
NO_REGIONS = (
    "The memory of this target is not known here, so say where to start and how much to read."
)
TRIM_TIP = (
    "Erased flash reads as FF. With this ticked, the FF bytes after the last\n"
    "byte that holds something are not saved, so the file is the size of\n"
    "what is there and not the size of the flash."
)


def parse_number(text: str) -> int | None:
    """A hexadecimal number as somebody would type it, or None if it is not one."""
    text = text.strip().replace("_", "").replace(" ", "")
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        return int(text, 16)
    except ValueError:
        return None


class ReadDialog(QDialog):
    def __init__(self, regions: Sequence[Region], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Read from the target")
        # Another address for the same memory would read the same bytes twice
        # over under a second name.
        self._regions = [r for r in regions if not r.alias_of]

        self.region = QComboBox()
        self.region.setAccessibleName("Region")
        for region in self._regions:
            self.region.addItem(
                f"{region.name} ({region.kind}, {size_text(region.length)} at {region.start:08X})"
            )
        self.region.addItem(OTHER)

        self.address = QLineEdit()
        self.address.setFont(fonts.mono())
        self.address.setAccessibleName("Address")
        self.address.setToolTip("Where to start reading, in hexadecimal.")
        self.length = QLineEdit()
        self.length.setFont(fonts.mono())
        self.length.setAccessibleName("Length")
        self.length.setToolTip("How many bytes to read, in hexadecimal.")
        self.size = QLabel()

        self.trim = QCheckBox("Leave off the erased bytes at the end")
        self.trim.setChecked(True)
        self.trim.setToolTip(TRIM_TIP)

        #: Why OK did nothing, when it did nothing. In the dialog rather
        #: than in a box on top of it.
        self.problem = QLabel()
        self.problem.setWordWrap(True)

        form = QFormLayout()
        if self._regions:
            form.addRow("Region:", self.region)
        form.addRow("Address:", self.address)
        form.addRow("Length:", self.length)
        form.addRow("", self.size)
        form.addRow("", self.trim)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Read...")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        if not self._regions:
            hint = QLabel(NO_REGIONS)
            hint.setWordWrap(True)
            layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)

        self.region.currentIndexChanged.connect(self._on_region)
        self.length.textChanged.connect(self._show_size)
        # The flash first: it is what is read back nine times in ten.
        flash = next((i for i, r in enumerate(self._regions) if r.kind == FLASH), 0)
        self.region.setCurrentIndex(flash)
        self._on_region(self.region.currentIndex())

    def _on_region(self, index: int) -> None:
        if 0 <= index < len(self._regions):
            region = self._regions[index]
            self.address.setText(f"{region.start:08X}")
            self.length.setText(f"{region.length:X}")

    def _show_size(self, _text: str = "") -> None:
        length = parse_number(self.length.text())
        self.size.setText(size_text(length) if length else "")

    def values(self) -> tuple[int, int, bool] | None:
        """The address, the length and whether to trim; None if they will not do."""
        address = parse_number(self.address.text())
        length = parse_number(self.length.text())
        if address is None or not 0 <= address <= 0xFFFF_FFFF:
            self.problem.setText("The address wants a hexadecimal number, such as 08000000.")
            return None
        if length is None or length <= 0:
            self.problem.setText("The length wants a hexadecimal number of bytes, such as 1000.")
            return None
        if address + length > 0x1_0000_0000:
            self.problem.setText("That runs past the end of a 32-bit address space.")
            return None
        self.problem.setText("")
        return address, length, self.trim.isChecked()

    def _accept(self) -> None:
        if self.values() is not None:
            self.accept()
