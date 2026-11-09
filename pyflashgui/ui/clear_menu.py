# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Clear on the right-click of a text pane, under the usual Copy and Select All.

Qt makes Copy and Select All, and gives them the system's own icons, which are
not the ones beside every other word in pyflashgui and stay when *Show icons*
is off. They are given pyflashgui's here, by the name Qt gives each.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QPlainTextEdit

from pyflashgui.ui import icons

#: Qt's own items in a text's menu, by the object name Qt gives each.
QT_ITEMS = {"edit-copy": icons.COPY, "select-all": icons.SELECT_ALL}


def menu(text: QPlainTextEdit) -> QMenu:
    """The standard menu for the text, with Clear at the bottom. Built apart from being shown."""
    built = text.createStandardContextMenu()
    for action in built.actions():
        if (name := QT_ITEMS.get(action.objectName())) is not None:
            icons.beside(action, name)
        elif not action.icon().isNull():
            action.setIcon(QIcon())  # one of Qt's with no picture of ours: the word alone
    built.addSeparator()
    icons.beside(built.addAction("Clear", text.clear), icons.CLEAR)
    return built


def add(text: QPlainTextEdit) -> QPlainTextEdit:
    """Give the text pane the menu above on its right-click."""

    def show(at: QPoint) -> None:
        shown = menu(text)
        shown.exec(text.viewport().mapToGlobal(at))
        shown.deleteLater()

    text.setContextMenuPolicy(Qt.CustomContextMenu)
    text.customContextMenuRequested.connect(show)
    return text
