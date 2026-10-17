# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A shorter copy of what a Memory pane shows: a range of it, or all of it but
the erased bytes at its end.

The copy is an entry of its own on the Files list, named after what it was
cropped from, unsaved, and shown in a pane of its own: so Save goes on saving
what is shown, and a copy is looked at, compared, saved or programmed like
anything else on the list.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core.flasher import size_text
from pyflashgui.ui import fonts
from pyflashgui.ui.read_dialog import parse_number

ERASED_TIP = (
    "What erased flash reads as on this target: as the target's description\n"
    "says, or FF or 00 where that is not right -- an XMC4500's reads 00, and\n"
    "pyOCD says FF for it. Kept for each target."
)


def without_erased(data: bytes, erased: int) -> bytes:
    """These bytes up to the last one that is not erased. An erased byte
    before it is part of what is there, and is kept."""
    return data.rstrip(bytes([erased]))


class CropDialog(QDialog):
    def __init__(
        self,
        address: int,
        data: bytes,
        erased_said: int,
        erased_chosen: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop")
        self._address = address
        self._data = data

        #: The usual reason: a whole flash read, of which the firmware is the start.
        self.erased = QRadioButton("All of it but the erased bytes at the end")
        self.range = QRadioButton("A range of it")
        group = QButtonGroup(self)
        group.addButton(self.erased)
        group.addButton(self.range)

        self.erased_as = QComboBox()
        self.erased_as.setToolTip(ERASED_TIP)
        self.erased_as.setAccessibleName("Erased flash reads as")
        for text, value in (
            (f"As the target says ({erased_said:02X})", None),
            ("FF", 0xFF),
            ("00", 0x00),
        ):
            self.erased_as.addItem(text, value)
        self.erased_as.setCurrentIndex(max(self.erased_as.findData(erased_chosen), 0))
        self._erased_said = erased_said

        self.start = QLineEdit(f"{address:08X}")
        self.start.setFont(fonts.mono())
        self.start.setAccessibleName("Start")
        self.start.setToolTip("Where the copy starts, in hexadecimal.")
        self.length = QLineEdit(f"{len(data):08X}")
        self.length.setFont(fonts.mono())
        self.length.setAccessibleName("Length")
        self.length.setToolTip("How many bytes it holds, in hexadecimal.")

        #: What OK would make, in words, as the choices change.
        self.kept = QLabel()
        #: Why OK would do nothing, when it would do nothing.
        self.problem = QLabel()
        self.problem.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self.erased)
        form.addRow("Erased flash reads as:", self.erased_as)
        form.addRow(self.range)
        form.addRow("Start:", self.start)
        form.addRow("Length:", self.length)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Crop")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        said = QLabel(
            f"A shorter copy of these {size_text(len(data))} from {address:08X}. It joins "
            "the Files list, named after what it is cropped from, to look at, compare or save."
        )
        said.setWordWrap(True)
        layout.addWidget(said)
        layout.addLayout(form)
        layout.addWidget(self.kept)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)

        self.erased.toggled.connect(self._show)
        self.erased_as.currentIndexChanged.connect(self._show)
        self.start.textChanged.connect(self._show)
        self.length.textChanged.connect(self._show)
        self.erased.setChecked(True)
        self._show()

    def erased_choice(self) -> int | None:
        """What was chosen for erased: a value, or None for the target's own."""
        chosen = self.erased_as.currentData()
        return None if chosen is None else int(chosen)

    def result(self) -> tuple[int, bytes] | None:
        """Where the copy starts and what it holds, or None if it would not do."""
        if self.erased.isChecked():
            erased = self.erased_choice()
            kept = without_erased(self._data, self._erased_said if erased is None else erased)
            if not kept:
                return self._refuse("All of it is erased, so there would be nothing left.")
            return self._address, kept
        start = parse_number(self.start.text())
        length = parse_number(self.length.text())
        end = self._address + len(self._data)
        if start is None or not self._address <= start < end:
            return self._refuse(
                f"The start wants an address from {self._address:08X} to {end - 1:08X}."
            )
        if length is None or length <= 0:
            return self._refuse("The length wants a hexadecimal number of bytes, such as 1000.")
        if start + length > end:
            return self._refuse(f"That runs past the end of what is shown, at {end - 1:08X}.")
        offset = start - self._address
        return start, self._data[offset : offset + length]

    def _refuse(self, why: str) -> None:
        self.problem.setText(why)
        return None

    def _show(self, *_args) -> None:
        self.erased_as.setEnabled(self.erased.isChecked())
        for field in (self.start, self.length):
            field.setEnabled(self.range.isChecked())
        self.problem.setText("")
        made = self.result()
        if made is None:
            self.kept.setText("")
        else:
            start, kept = made
            self.kept.setText(
                f"Keeps {start:08X} to {start + len(kept) - 1:08X}, {size_text(len(kept))}."
            )
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(made is not None)

    def _accept(self) -> None:
        if self.result() is not None:
            self.accept()
