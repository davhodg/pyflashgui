# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Tools > Settings > Time on Event Log lines: the time of day in front of each line."""

import re
from datetime import datetime

import pytest
from PySide6.QtCore import QSettings

from pyflashgui.ui import main_window
from pyflashgui.ui.main_window import MainWindow


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    QSettings().clear()
    win = MainWindow()
    yield win
    win.close()


def line_of(window, said: str) -> str:
    """The line that says this: the offscreen platform writes lines of its own."""
    return next(line for line in window.log.toPlainText().splitlines() if said in line)


def test_lines_carry_no_time_unless_chosen(window, app):
    window.events.warning("plain")
    app.processEvents()
    assert line_of(window, "plain") == "plain"
    assert not window.log_times_action.isChecked()
    assert not re.search(r"^\d\d:\d\d:\d\d ", window.log.toPlainText(), re.M), "on no line"


def test_a_chosen_time_is_the_time_of_day_to_the_second_and_kept_when_copied(
    window, app, monkeypatch
):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 2, 14, 3, 27, 900000)

    monkeypatch.setattr(main_window, "datetime", Clock)
    window.log_times_action.setChecked(True)
    window.events.warning("the probe did not answer")
    app.processEvents()
    said = line_of(window, "the probe did not answer")
    assert said == "14:03:27 the probe did not answer", "to the second"
    window.log.selectAll()
    window.log.copy()
    assert "14:03:27 the probe did not answer" in app.clipboard().text()


def test_the_choice_is_kept_for_the_next_window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    QSettings().clear()
    first = MainWindow()
    try:
        first.log_times_action.setChecked(True)
    finally:
        first.close()
        first.deleteLater()
    second = MainWindow()
    try:
        assert second.log_times_action.isChecked()
        assert second.log_times_action in second.settings_menu.actions(), "Tools > Settings"
        second.log_times_action.setChecked(False)
    finally:
        second.close()
        second.deleteLater()
