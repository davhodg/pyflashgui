# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A button in two parts: what is done every time, and what is chosen now and then.

Pressing it does the thing. The small arrow beside it opens a menu of what
goes with the thing and is wanted less often -- programming without the
verify, beside the button that does both. Two buttons for that pair spent a
row's width on the one pressed rarely; a tick box beside them said what the
button would do somewhere other than on the button.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QPushButton, QToolButton


class SplitButton(QToolButton):
    """Pressed, it calls ``pressed``; its arrow opens the menu ``add`` fills."""

    def __init__(self, text: str, tip: str, pressed: Callable[[], None]) -> None:
        super().__init__()
        self.setText(text)
        self.setToolTip(tip)
        self.setPopupMode(QToolButton.MenuButtonPopup)
        self.clicked.connect(lambda _checked=False: pressed())
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        self.setMenu(menu)
        # As tall as an ordinary button, which it sits in a row with: a tool
        # button is drawn shorter.
        self.setMinimumHeight(QPushButton(text).sizeHint().height())

    def add(self, text: str, tip: str, chosen: Callable[[], None]) -> QAction:
        action = self.menu().addAction(text)
        action.setToolTip(tip)
        action.triggered.connect(lambda _checked=False: chosen())
        return action
