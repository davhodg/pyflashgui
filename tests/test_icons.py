# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Icons beside the words: shipped with pyflashgui, and drawn in the text colour."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialogButtonBox, QPushButton

from pyflashgui import resources
from pyflashgui.ui import icons

SIZE = 20


def drawn_colours(icon: QIcon, mode=QIcon.Normal) -> set[str]:
    """The colours of the pixels the icon covers fully."""
    image = icon.pixmap(SIZE, SIZE, mode).toImage()
    return {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() == 255
    }


def test_every_name_has_a_picture_that_loads():
    for name in icons.FILE:
        assert QSvgRenderer(str(icons.path(name))).isValid(), name


def test_every_picture_shipped_is_used():
    shipped = {file.stem for file in resources.path("icons").glob("*.svg")}
    assert shipped == set(icons.FILE.values())


def test_a_button_given_one_has_it(app, monkeypatch):
    monkeypatch.setattr(icons, "_shown", True)
    for name in icons.FILE:
        assert not icons.beside(QPushButton(), name).icon().isNull(), name


def test_turned_off_a_button_keeps_the_word_alone(app, monkeypatch):
    monkeypatch.setattr(icons, "_shown", False)
    button = icons.beside(QPushButton("Erase..."), icons.ERASE)
    assert button.icon().isNull()
    assert button.property(icons.PROPERTY) == icons.ERASE


def test_turning_them_off_and_on_takes_them_away_and_puts_them_back(app, monkeypatch):
    monkeypatch.setattr(icons, "_shown", True)
    monkeypatch.setattr(QSettings, "setValue", lambda *_args: None)
    button = icons.beside(QPushButton("Save..."), icons.SAVE)
    icons.set_shown(False)
    assert button.icon().isNull() and button.text() == "Save..."
    icons.set_shown(True)
    assert not button.icon().isNull()


def test_a_dialogs_own_buttons_are_given_theirs(app, monkeypatch):
    monkeypatch.setattr(icons, "_shown", True)
    box = icons.on_buttons(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
    assert box.button(QDialogButtonBox.Ok).property(icons.PROPERTY) == icons.CHECK
    assert box.button(QDialogButtonBox.Cancel).property(icons.PROPERTY) == icons.CANCEL


def test_a_button_given_its_own_keeps_it(app, monkeypatch):
    monkeypatch.setattr(icons, "_shown", True)
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    icons.beside(box.button(QDialogButtonBox.Ok), icons.READ).setText("Read")
    icons.on_buttons(box)
    assert box.button(QDialogButtonBox.Ok).property(icons.PROPERTY) == icons.READ


def test_it_is_drawn_in_the_text_colour_not_the_files(app):
    text = QGuiApplication.palette().color(QPalette.Active, QPalette.ButtonText).name()
    assert drawn_colours(icons.icon(icons.STOP)) == {text}


def test_disabled_it_is_drawn_in_the_disabled_text_colour(app, monkeypatch):
    palette = QPalette(QGuiApplication.palette())
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#ff0000"))
    monkeypatch.setattr(QGuiApplication, "palette", staticmethod(lambda: palette))
    assert drawn_colours(icons.icon(icons.STOP), QIcon.Disabled) == {"#ff0000"}


def test_a_new_palette_recolours_an_icon_already_made(app, monkeypatch):
    made = icons.icon(icons.STOP)
    palette = QPalette(QGuiApplication.palette())
    palette.setColor(QPalette.Active, QPalette.ButtonText, QColor("#00ff00"))
    monkeypatch.setattr(QGuiApplication, "palette", staticmethod(lambda: palette))
    assert drawn_colours(made) == {"#00ff00"}


# --- the right-click of a text pane ---------------------------------------------------
def test_copy_and_select_all_are_given_ours_and_clear_is_added(app, monkeypatch):
    from PySide6.QtWidgets import QPlainTextEdit

    from pyflashgui.ui import clear_menu

    monkeypatch.setattr(icons, "_shown", True)
    text = QPlainTextEdit("a line")
    text.setReadOnly(True)
    text.selectAll()
    menu = clear_menu.menu(text)
    given = {a.objectName() or a.text(): a.property(icons.PROPERTY) for a in menu.actions()}
    assert given["edit-copy"] == icons.COPY
    assert given["select-all"] == icons.SELECT_ALL
    assert given["Clear"] == icons.CLEAR
    menu.actions()[-1].trigger()
    assert text.toPlainText() == ""
