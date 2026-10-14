# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""File > Run script... and File > Recent scripts."""

import pytest
from PySide6.QtCore import QSettings

from pyflashgui.ui import folders, messages
from pyflashgui.ui.scripts_menu import MOST_RECENT


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from pyflashgui.ui.main_window import MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()
    made = MainWindow()
    made.said = []
    made.events.posted.connect(lambda message, level: made.said.append((level, message)))
    yield made
    made.close()


def script(folder, name="test.py", text="print('ran', 6 * 7)\n"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_run_script_runs_it_in_the_console_and_shows_the_console(window, tmp_path, monkeypatch):
    path = script(tmp_path)
    monkeypatch.setattr(folders, "open_file", lambda *a, **k: str(path))
    window.scripts_menu.run_action.trigger()
    assert "ran 42" in window.console.output.toPlainText()
    assert not window.panes.docks["console"].isHidden(), "where what it printed is"


def test_what_was_run_is_listed_newest_first_once_each(window, tmp_path):
    first, second = script(tmp_path, "a.py"), script(tmp_path, "b.py")
    for path in (first, second, first):
        window.run_script_in_console(str(path))
    assert window.scripts_menu.recent() == [first.resolve(), second.resolve()]


def test_the_consoles_own_button_is_remembered_too(window, tmp_path):
    path = script(tmp_path)
    window.console.run_file(str(path))
    assert window.scripts_menu.recent() == [path.resolve()]


def test_only_the_last_few_are_kept(window, tmp_path):
    paths = [script(tmp_path, f"s{n}.py") for n in range(MOST_RECENT + 2)]
    for path in paths:
        window.run_script_in_console(str(path))
    assert window.scripts_menu.recent() == [p.resolve() for p in reversed(paths)][:MOST_RECENT]


def test_a_recent_script_runs_from_the_menu(window, tmp_path):
    path = script(tmp_path)
    window.run_script_in_console(str(path))
    window.console.output.clear()
    menu = window.scripts_menu.recent_menu
    menu.aboutToShow.emit()
    menu.actions()[0].trigger()
    assert "ran 42" in window.console.output.toPlainText()


def test_an_empty_list_says_so(window):
    menu = window.scripts_menu.recent_menu
    menu.aboutToShow.emit()
    assert [(a.text(), a.isEnabled()) for a in menu.actions()] == [("No scripts run yet", False)]


def test_one_that_has_gone_is_said_and_taken_off(window, tmp_path, monkeypatch):
    path = script(tmp_path)
    window.run_script_in_console(str(path))
    path.unlink()
    said = []
    monkeypatch.setattr(messages, "warning", lambda *a, **k: said.append(a))
    window.scripts_menu.run_recent(path.resolve())
    assert said and window.scripts_menu.recent() == []


def test_one_in_the_workspace_is_remembered_relative_to_it(window):
    """So a workspace taken to another computer still finds its own scripts."""
    folder = window.ctx.workspace_dir / "scripts"
    folder.mkdir(parents=True, exist_ok=True)
    path = script(folder)
    window.run_script_in_console(str(path))
    assert window.ctx.settings.get("scripts.recent") == ["scripts/test.py"]
    assert window.scripts_menu.recent() == [window.ctx.workspace_dir / "scripts" / "test.py"]


def test_one_is_not_started_while_another_runs(window, tmp_path):
    inner = script(tmp_path, "inner.py")
    outer = script(tmp_path, "outer.py", f"window.run_script_in_console({str(inner)!r})\n")
    window.run_script_in_console(str(outer))
    assert "ran 42" not in window.console.output.toPlainText()
    assert any("inner.py was not run" in message for _level, message in window.said)
