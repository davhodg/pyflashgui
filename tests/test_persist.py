# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Settled choices survive a restart; passing state does not."""

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

from pyflashgui.core.context import Context
from pyflashgui.ui.main_window import MainWindow
from pyflashgui.ui.persist import remember


@pytest.fixture
def ctx(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    return Context()


# --- the binder ----------------------------------------------------------------------
def test_a_checkbox_is_restored(app, ctx):
    box = QCheckBox()
    remember(ctx, "k.box", box)
    box.setChecked(True)

    again = QCheckBox()
    remember(ctx, "k.box", again)
    assert again.isChecked()


def test_a_combo_is_stored_by_text_not_index(app, ctx):
    """A list that gains an entry must not silently change what was chosen."""
    first = QComboBox()
    first.addItems(["Alpha", "Beta"])
    remember(ctx, "k.combo", first)
    first.setCurrentText("Beta")

    grown = QComboBox()
    grown.addItems(["New", "Alpha", "Beta"])  # everything has shifted along
    remember(ctx, "k.combo", grown)
    assert grown.currentText() == "Beta"


def test_spin_boxes_keep_their_type(app, ctx):
    whole, fractional = QSpinBox(), QDoubleSpinBox()
    whole.setRange(0, 100)
    fractional.setRange(0.0, 100.0)
    remember(ctx, "k.int", whole)
    remember(ctx, "k.float", fractional)
    whole.setValue(42)
    fractional.setValue(2.5)

    whole2, fractional2 = QSpinBox(), QDoubleSpinBox()
    whole2.setRange(0, 100)
    fractional2.setRange(0.0, 100.0)
    remember(ctx, "k.int", whole2)
    remember(ctx, "k.float", fractional2)
    assert whole2.value() == 42
    assert fractional2.value() == pytest.approx(2.5)


def test_restoring_a_value_does_not_count_as_changing_it(app, ctx):
    box = QCheckBox()
    box.setChecked(True)
    remember(ctx, "k.default", box)
    assert ctx.settings.get("k.default") is None, "nothing was chosen, so nothing is stored"


def test_the_widget_supplies_its_own_default(app, ctx):
    box = QCheckBox()
    box.setChecked(True)
    remember(ctx, "k.unset", box)
    assert box.isChecked(), "an unset key must leave the widget as it was built"


def test_a_hand_edited_value_of_the_wrong_type_is_ignored(app, ctx):
    ctx.settings.set("k.spin", "not a number")
    spin = QSpinBox()
    spin.setValue(7)
    remember(ctx, "k.spin", spin)
    assert spin.value() == 7


def test_an_unsupported_widget_is_refused_loudly(app, ctx):
    from PySide6.QtWidgets import QPushButton

    with pytest.raises(TypeError, match="QPushButton"):
        remember(ctx, "k.button", QPushButton())


def test_a_line_edit_saves_when_editing_finishes(app, ctx):
    line = QLineEdit()
    remember(ctx, "k.line", line)
    line.setText("typed")
    assert ctx.settings.get("k.line") is None, "not on every keystroke"
    line.editingFinished.emit()
    assert ctx.settings.get("k.line") == "typed"


# --- the window ----------------------------------------------------------------------
@pytest.fixture
def fresh_window(app, tmp_path, monkeypatch):
    def build():
        monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
        QSettings().clear()
        return MainWindow()

    return build
