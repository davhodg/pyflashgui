# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The layout a first run opens with, and what Reset layout goes back to."""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QSettings, Qt

from pyflashgui.core import workspaces
from pyflashgui.core.layout import Layout
from pyflashgui.core.settings import Settings
from pyflashgui.ui import probe_bar
from pyflashgui.ui.main_window import DEFAULT_VISIBLE, LAYOUT_VERSION, MainWindow

PROBE = "SIM0001"


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


@pytest.fixture
def home(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()  # a first run, whatever ran before
    settings = Settings(workspaces.settings_path())
    settings.set(probe_bar.BACKEND_KEY, "simulated")
    settings.set(probe_bar.TARGET_KEY, "sim_single")
    return tmp_path


def opened(app):
    win = MainWindow()
    win.resize(1400, 900)
    win.show()  # a dock of a window that was never shown reports itself hidden
    wait_for(lambda: win.probe_bar.chosen_probe() == PROBE and win.flasher.regions)
    app.processEvents()
    return win


def close(win):
    wait_for(lambda: not win.flasher.busy)
    win.close()
    QCoreApplication.processEvents()


@pytest.fixture
def window(app, home):
    win = opened(app)
    yield win
    close(win)


def visible(window) -> set[str]:
    return {name for name, dock in window.panes.docks.items() if dock.isVisible()}


def test_only_the_files_and_the_log_are_open_to_start_with(app, window):
    """The console is for somebody who asks for it, and a Memory pane is
    opened from the Files pane; until one is, its place says how."""
    assert visible(window) == set(DEFAULT_VISIBLE) == {"files", "log"}
    assert window.memory_space.isVisible()


def test_the_default_layout_is_the_one_drawn_in_arrange_default(app, window):
    """Files beside the place for the Memory panes, and the log under both,
    because its lines are long."""
    files, log, space = (
        dock.geometry()
        for dock in (window.panes.docks["files"], window.panes.docks["log"], window.memory_space)
    )
    assert space.x() > files.x(), "the Memory panes go to the right of the Files pane..."
    assert space.y() == files.y(), "...in the same row"
    assert log.y() > files.y() and log.y() > space.y(), "the log is under both..."
    assert log.width() > files.width() and log.width() > space.width(), "...spanning them"


def test_the_log_gets_less_room_than_the_files_pane(app, window):
    """The log is glanced at; the Files pane, with its map, is worked in."""
    files, log = (window.panes.docks[n].geometry() for n in ("files", "log"))
    assert files.height() > log.height()


def test_the_files_pane_takes_about_half_of_the_width(app, window):
    """The complaint the place for the Memory panes answers is the Files pane
    taking the whole width, so the share is stated at both ends."""
    files, space = window.panes.docks["files"].geometry(), window.memory_space.geometry()
    share = files.width() / (files.width() + space.width())
    assert 0.35 < share < 0.65, f"the Files pane has {share:.0%} of the width"


def test_a_hidden_pane_comes_back_where_it_belongs(app, window):
    window.panes._note_arranged("console")  # placed before: not a first time
    dock = window.panes.docks["console"]
    assert not dock.isVisible()
    window.panes.show("console")
    app.processEvents()
    assert dock.isVisible() and not dock.isFloating()
    assert window.dockWidgetArea(dock) == Qt.BottomDockWidgetArea


def test_reset_layout_puts_the_console_away_again(app, window):
    window.panes._note_arranged("console")
    window.panes.show("console")
    window.panes.docks["log"].setFloating(True)
    app.processEvents()
    window._reset_layout()
    app.processEvents()
    assert visible(window) == set(DEFAULT_VISIBLE)
    assert not window.panes.docks["log"].isFloating()
    assert window.memory_space.isVisible()


def shares(window) -> dict[str, float]:
    docks = {"files": window.panes.docks["files"], "log": window.panes.docks["log"]}
    docks["space"] = window.memory_space
    heights = {n: d.geometry().height() for n, d in docks.items()}
    widths = {n: d.geometry().width() for n, d in docks.items()}
    return {
        **{f"{n} high": round(h / sum(heights.values()), 2) for n, h in heights.items()},
        **{f"{n} wide": round(w / sum(widths.values()), 2) for n, w in widths.items()},
    }


def test_reset_layout_gives_the_same_shares_as_a_fresh_window(app, window):
    """Reset layout once restored a saveState captured during construction,
    before the window had ever been shown, so the sizes in it were the ones
    Qt had not worked out yet: one pane filled the window and the rest were
    a strip. Proportions rather than pixels, because reset also puts the
    window back to the size it opens at."""
    before = shares(window)

    window.panes._note_arranged("console")
    window.panes.show("console")
    window.resizeDocks([window.panes.docks["files"]], [900], Qt.Horizontal)
    app.processEvents()
    window._reset_layout()
    app.processEvents()

    after = shares(window)
    for key, share in before.items():
        assert after[key] == pytest.approx(share, abs=0.03), f"{key}: {before} -> {after}"


def test_a_layout_from_an_older_version_gives_way_to_the_default_and_says_so(app, home):
    """Restored as it was, a layout from before the panes changed puts them
    anywhere; the default is put in its place, once, with a word about why."""
    first = opened(app)
    first.panes.docks["log"].setFloating(True)
    app.processEvents()
    older = bytes(first.saveState(LAYOUT_VERSION - 1))
    close(first)
    # As the version before this one wrote it, over what closing just saved.
    Layout(workspaces.layout_path()).set("window", older)

    second = opened(app)
    assert visible(second) == set(DEFAULT_VISIBLE)
    assert not second.panes.docks["log"].isFloating()
    assert "from a version with a different set of panes" in second.log.toPlainText()
    close(second)
