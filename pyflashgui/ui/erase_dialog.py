# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""How much of a target's flash to erase.

All of it, some of its regions, or a range of addresses. All of it is what
the dialog opens on, because it is what Erase has always meant; the other two
are for a device with more than one flash, where the bootloader or the data
is to be kept.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core.flasher import size_text
from pyflashgui.core.memory_map import FLASH, Region
from pyflashgui.ui import fonts
from pyflashgui.ui.read_dialog import parse_number

SECTORS = (
    "Flash is erased a sector at a time, so every sector that any of a range falls in is "
    "erased whole."
)


class EraseDialog(QDialog):
    def __init__(self, regions: Sequence[Region], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Erase flash")
        self._flash = [r for r in regions if r.kind == FLASH and not r.alias_of]

        self.everything = QRadioButton("All of the flash")
        self.everything.setChecked(True)
        self.some = QRadioButton("These regions:")
        self.range = QRadioButton("This range:")

        self.regions = QListWidget()
        self.regions.setAccessibleName("Flash regions to erase")
        for region in self._flash:
            item = QListWidgetItem(
                f"{region.name}: {size_text(region.length)} at {region.start:08X}"
            )
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)
            self.regions.addItem(item)
        if self._flash:
            rows = min(len(self._flash), 6)
            self.regions.setMaximumHeight(
                rows * self.regions.sizeHintForRow(0) + 2 * self.regions.frameWidth() + 4
            )
        # Ticking a region is choosing to erase by region: the button is
        # not made to be pressed first.
        self.regions.itemChanged.connect(lambda _item: self.some.setChecked(True))

        self.address = QLineEdit()
        self.address.setFont(fonts.mono())
        self.address.setAccessibleName("Address")
        self.address.setToolTip("Where to start erasing, in hexadecimal.")
        self.length = QLineEdit()
        self.length.setFont(fonts.mono())
        self.length.setAccessibleName("Length")
        self.length.setToolTip("How many bytes to erase, in hexadecimal.")
        for box in (self.address, self.length):
            box.textEdited.connect(lambda _text: self.range.setChecked(True))
        form = QFormLayout()
        form.addRow("Address:", self.address)
        form.addRow("Length:", self.length)

        note = QLabel(SECTORS)
        note.setWordWrap(True)
        #: Why OK did nothing, when it did nothing.
        self.problem = QLabel()
        self.problem.setWordWrap(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Erase...")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.everything)
        # With no regions known there are none to tick, and the choice of
        # them would be a choice of nothing.
        if self._flash:
            layout.addWidget(self.some)
            layout.addWidget(self.regions)
        layout.addWidget(self.range)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)

    def chosen(self) -> tuple[bool, list[tuple[int, int]] | None]:
        """Whether the choice will do, and what it is.

        The ranges as (address, length), or None for all of the flash. With
        a choice that will not do, why not is put in the dialog.
        """
        self.problem.setText("")
        if self.everything.isChecked():
            return True, None
        if self.some.isChecked():
            ticked = [
                (region.start, region.length)
                for index, region in enumerate(self._flash)
                if self.regions.item(index).checkState() == Qt.Checked
            ]
            if not ticked:
                self.problem.setText("Tick the regions to erase.")
                return False, None
            return True, ticked
        address = parse_number(self.address.text())
        length = parse_number(self.length.text())
        if address is None or not 0 <= address <= 0xFFFF_FFFF:
            self.problem.setText("The address wants a hexadecimal number, such as 08000000.")
            return False, None
        if length is None or length <= 0:
            self.problem.setText("The length wants a hexadecimal number of bytes, such as 1000.")
            return False, None
        if address + length > 0x1_0000_0000:
            self.problem.setText("That runs past the end of a 32-bit address space.")
            return False, None
        return True, [(address, length)]

    def _accept(self) -> None:
        if self.chosen()[0]:
            self.accept()
