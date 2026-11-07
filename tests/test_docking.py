# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Undocked panes: left as Qt makes them, with two buttons on the pane itself.

The Python Console and the Event Log stand in for any pane: they are the two
that are always there and are not the Files pane, which the place kept for the
Memory panes is arranged around.
"""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QRect, QSettings, Qt

from pyflashgui.core import workspaces
from pyflashgui.core.settings import Settings
from pyflashgui.ui import probe_bar
from pyflashgui.ui.main_window import MainWindow

PROBE = "SIM0001"


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def placed(win):
    """Every pane placed before, so the console shown here docks or floats as
    these tests make it, rather than opening in front of the window the first
    time -- which tests/test_console.py covers."""
    for name in win.panes.docks:
        win.panes._note_arranged(name)


@pytest.fixture
def home(app, tmp_path, monkeypatch):
    """A first run on the simulated probe, so nothing looks for a real one."""
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()
    settings = Settings(workspaces.settings_path())
    settings.set(probe_bar.BACKEND_KEY, "simulated")
    settings.set(probe_bar.TARGET_KEY, "sim_single")
    return tmp_path


def restart(app, previous=None, arrange=True):
    """Close a window if given, then open a fresh one on the same settings."""
    if previous is not None:
        close(previous)
    win = MainWindow()
    if arrange:
        placed(win)
    win.show()
    wait_for(lambda: win.probe_bar.chosen_probe() == PROBE and win.flasher.regions)
    settle(app, 10)
    return win


def close(win):
    wait_for(lambda: not win.flasher.busy)
    win.close()
    QCoreApplication.processEvents()


@pytest.fixture
def window(app, home):
    win = restart(app)
    yield win
    close(win)


def settle(app, times=5):
    for _ in range(times):
        app.processEvents()


def float_out(app, dock):
    dock.setVisible(True)
    dock.setFloating(True)
    settle(app)


# --- floating is Qt's own, untouched --------------------------------------------------
def test_floating_is_left_as_qt_makes_it(app, window):
    """Promoting a floated pane to a plain window cost more than it bought."""
    dock = window.panes.docks["console"]
    float_out(app, dock)
    assert dock.isFloating()
    assert not dock.windowFlags() & Qt.WindowStaysOnTopHint, "not until it is asked for"


def test_docking_again_still_works(app, window):
    dock = window.panes.docks["console"]
    float_out(app, dock)
    dock.setFloating(False)
    settle(app)
    assert not dock.isFloating()
    assert window.dockWidgetArea(dock) != Qt.NoDockWidgetArea


# --- the Ctrl tip ---------------------------------------------------------------------
def test_the_ctrl_tip_is_said_once(app, window):
    float_out(app, window.panes.docks["console"])
    assert "Hold Ctrl" in window.log.toPlainText()
    before = window.log.toPlainText().count("Hold Ctrl")

    float_out(app, window.panes.docks["log"])
    assert window.log.toPlainText().count("Hold Ctrl") == before, "said once, not per pane"


def test_a_hidden_floating_pane_is_not_worth_a_tip(app, home):
    """A pane undocked and then closed is restored floating but hidden.

    That said "hold Ctrl while dragging" at every start-up, with nothing on
    screen to say it about.
    """
    first = restart(app)
    dock = first.panes.docks["console"]
    float_out(app, dock)
    dock.close()  # undocked, then shut
    settle(app)

    second = restart(app, first, arrange=False)
    restored = second.panes.docks["console"]
    assert restored.isFloating() and not restored.isVisible(), "the case in question"
    assert "Hold Ctrl" not in second.log.toPlainText()
    assert not second.panes.bars["console"].isVisible(), "and no buttons for a pane nobody sees"
    close(second)


# --- the buttons ----------------------------------------------------------------------
def test_the_buttons_are_hidden_while_the_pane_is_docked(app, window):
    window.panes.docks["console"].setVisible(True)
    settle(app)
    assert not window.panes.bars["console"].isVisible()


def test_undocking_shows_them(app, window):
    float_out(app, window.panes.docks["console"])
    assert window.panes.bars["console"].isVisible()


def test_each_button_says_what_pressing_it_will_do(app, window):
    """Detach, then Attach: the one button does both."""
    float_out(app, window.panes.docks["console"])
    bar = window.panes.bars["console"]

    assert bar.move_button.text() == "Detach"
    bar.move_button.click()
    settle(app)
    assert "console" in window.panes.detached
    assert bar.move_button.text() == "Attach"
    bar.move_button.click()
    settle(app)
    assert "console" not in window.panes.detached
    # Back where it came from, which was floating, so it is still out and
    # still carries its buttons.
    assert bar.isVisible()


def test_the_pin_button_keeps_the_pane_on_top(app, window):
    dock = window.panes.docks["console"]
    float_out(app, dock)
    window.panes.bars["console"].pin.setChecked(True)
    settle(app)
    assert dock.windowFlags() & Qt.WindowStaysOnTopHint
    assert window.panes.bars["console"].pin.text() == "Unpin"


def test_detaching_says_nothing_in_the_log(app, window):
    """A window appearing is its own announcement."""
    float_out(app, window.panes.docks["console"])
    before = window.log.toPlainText()
    window.panes.bars["console"].move_button.click()
    settle(app)
    assert window.log.toPlainText() == before


# --- detaching ------------------------------------------------------------------------
def test_detaching_gives_the_pane_a_window_with_no_parent(app, window):
    """An owned window is the thing Windows keeps out of the taskbar."""
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)

    detached = window.panes.detached["console"]
    assert detached.parent() is None, "an owner is what costs it the taskbar entry"
    assert detached.isVisible()
    assert detached.pane.isAncestorOf(window.console), "the pane moved, not a copy"
    # Checking the window and not what is inside it is how a window with a
    # title, a taskbar entry and nothing in it got through.
    assert detached.pane.isVisible(), "a detached pane must not be a blank window"
    assert window.panes.docks["console"].widget() is None
    assert not window.panes.docks["console"].isVisible()


def test_closing_a_detached_pane_closes_it(app, window):
    """Closing a window means closing it, as it does for a docked pane."""
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)

    window.panes.detached["console"].close()
    settle(app)
    dock = window.panes.docks["console"]
    assert "console" not in window.panes.detached
    assert not dock.isVisible(), "closed means closed, not docked"
    assert not window.panes.on_screen("console"), "and the View menu agrees"
    assert dock.widget() is not None, "the pane went home even so"


def test_the_view_menu_shows_it_again_in_its_own_window(app, window):
    """Closed while detached, it came back docked: the detaching was forgotten."""
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)
    window.panes.detached["console"].close()
    settle(app)

    dock = window.panes.docks["console"]
    dock.toggleViewAction().trigger()
    settle(app)
    assert "console" in window.panes.detached
    assert window.panes.detached["console"].isVisible()
    assert window.panes.detached["console"].pane.isVisible(), "the pane, not a blank window"
    assert not dock.isVisible(), "and no empty dock beside it"


def test_a_pane_closed_detached_opens_detached_after_a_restart(app, home):
    first = restart(app)
    float_out(app, first.panes.docks["console"])
    first.panes.detach("console")
    settle(app)
    first.panes.detached["console"].close()
    settle(app)

    second = restart(app, first, arrange=False)
    assert "console" not in second.panes.detached, "closed, so it does not open by itself"
    second.panes.show("console")
    settle(app)
    assert "console" in second.panes.detached
    close(second)


def test_attach_puts_it_back_in_the_window_for_good(app, window):
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)
    window.panes.bars["console"].move_button.click()  # Attach
    settle(app)
    dock = window.panes.docks["console"]
    dock.toggleViewAction().trigger()  # put away
    settle(app)

    dock.toggleViewAction().trigger()  # and brought back
    settle(app)
    assert "console" not in window.panes.detached
    assert dock.isVisible()


def test_attaching_from_the_button_shows_it(app, window):
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)

    window.panes.bars["console"].move_button.click()
    settle(app)
    dock = window.panes.docks["console"]
    assert "console" not in window.panes.detached
    assert dock.isVisible() and dock.widget().isVisible()
    assert dock.isFloating(), "it was floating before it was detached"


def test_the_pane_is_still_shown_after_a_round_trip(app, window):
    """Out and back twice: each reparent hides it again, so each needs undoing."""
    for _ in range(2):
        float_out(app, window.panes.docks["console"])
        window.panes.detach("console")
        settle(app)
        assert window.panes.detached["console"].pane.isVisible()
        window.panes.attach("console")
        settle(app)
        assert window.panes.docks["console"].widget().isVisible()


def test_dock_all_panes_collects_detached_ones_too(app, window):
    float_out(app, window.panes.docks["console"])
    float_out(app, window.panes.docks["log"])
    window.panes.detach("console")
    settle(app)

    window.panes.dock_all()
    settle(app)
    assert not window.panes.detached
    assert not any(d.isFloating() for d in window.panes.docks.values())


def test_closing_the_main_window_closes_detached_panes(app, home):
    """They have no parent, so they would keep the application running."""
    win = restart(app)
    float_out(app, win.panes.docks["console"])
    win.panes.detach("console")
    settle(app)
    detached = win.panes.detached["console"]

    close(win)
    assert not detached.isVisible()
    assert not win.panes.detached


# --- pinning must not empty the window it is pinning ----------------------------------
def test_pinning_a_detached_pane_keeps_its_contents(app, window):
    """Changing a window flag rebuilds the window and hides what is in it.

    Worse, it hides the window itself, so a visibility check *after* the
    change is always told it is hidden -- nothing was shown again, and
    pressing Pin emptied the window, taking the button with it.
    """
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)
    detached = window.panes.detached["console"]
    bar = window.panes.bars["console"]

    for wanted in (True, False, True):
        bar.pin.setChecked(wanted)
        settle(app)
        assert bool(detached.windowFlags() & Qt.WindowStaysOnTopHint) is wanted
        assert detached.isVisible(), "the window itself must survive being pinned"
        assert detached.pane.isVisible(), "and what is in it"
        assert bar.isVisible(), "including the button that was just pressed"


def test_pinning_a_floating_pane_keeps_its_contents(app, window):
    dock = window.panes.docks["console"]
    float_out(app, dock)
    bar = window.panes.bars["console"]

    for wanted in (True, False, True):
        bar.pin.setChecked(wanted)
        settle(app)
        assert bool(dock.windowFlags() & Qt.WindowStaysOnTopHint) is wanted
        assert dock.widget().isVisible()
        assert bar.isVisible()


def test_pinning_one_of_several_undocked_panes_leaves_the_others(app, window):
    console, log = window.panes.docks["console"], window.panes.docks["log"]
    float_out(app, console)
    float_out(app, log)

    window.panes.bars["console"].pin.setChecked(True)
    settle(app)
    assert console.windowFlags() & Qt.WindowStaysOnTopHint
    assert not log.windowFlags() & Qt.WindowStaysOnTopHint, "one pin, one pane"
    assert window.panes.bars["log"].isVisible() and not window.panes.bars["log"].pin.isChecked()


# --- what survives a restart ----------------------------------------------------------
def test_a_pane_restored_floating_has_its_buttons(app, home):
    """A restored pane is shown after topLevelChanged says it is floating.

    Asking then found it invisible and left it with no buttons at all, on a
    pane sitting in plain sight.
    """
    first = restart(app)
    float_out(app, first.panes.docks["console"])
    first.panes.bars["console"].pin.setChecked(True)
    settle(app)

    second = restart(app, first, arrange=False)
    dock = second.panes.docks["console"]
    assert dock.isFloating() and dock.isVisible()
    assert second.panes.bars["console"].isVisible(), "an undocked pane must carry its buttons"
    assert second.panes.bars["console"].pin.isChecked(), "and remember it was pinned"
    close(second)


def test_a_detached_pane_comes_back_detached(app, home):
    """It came back closed: putting it away on the way out was the last thing
    saved about it."""
    first = restart(app)
    float_out(app, first.panes.docks["console"])
    first.panes.detach("console")
    settle(app)

    second = restart(app, first, arrange=False)
    assert "console" in second.panes.detached, "left on another screen, so put it back there"
    assert second.panes.detached["console"].isVisible()
    assert second.panes.detached["console"].pane.isVisible()
    assert second.panes.bars["console"].isVisible()
    close(second)


def test_attaching_returns_a_pane_to_where_it_was(app, window):
    """It was undocked before it was detached, so that is where it goes back."""
    dock = window.panes.docks["console"]
    float_out(app, dock)
    window.panes.detach("console")
    settle(app)

    window.panes.bars["console"].move_button.click()  # Attach
    settle(app)
    assert dock.isFloating(), "the main window is not where it came from"
    assert dock.isVisible()
    assert window.panes.bars["console"].isVisible(), "still out, so still has its buttons"


def test_attaching_a_pane_detached_from_docked_docks_it(app, window):
    """And one that was docked goes back to being docked."""
    dock = window.panes.docks["log"]
    assert dock.isVisible() and not dock.isFloating()
    window.panes.detach("log")
    settle(app)

    window.panes.attach("log")
    settle(app)
    assert not dock.isFloating()
    assert dock.isVisible()
    assert not window.panes.bars["log"].isVisible(), "docked panes carry no buttons"


def test_a_detached_pane_leaves_no_empty_dock_behind(app, home):
    """Starting up with a detached pane showed an empty one in the main window.

    Qt shows a restored floating dock *after* the layout is put back, which is
    after the pane has been taken out of it -- so hiding it once, at the moment
    of detaching, was not enough.
    """
    first = restart(app)
    float_out(app, first.panes.docks["console"])
    first.panes.bars["console"].pin.setChecked(True)
    first.panes.detach("console")
    settle(app)

    second = restart(app, first, arrange=False)
    dock = second.panes.docks["console"]
    assert "console" in second.panes.detached
    assert not dock.isVisible(), "an emptied dock must not be left on screen"
    assert dock.widget() is None, "because the pane is in the window of its own"
    assert second.panes.detached["console"].pane.isVisible()
    assert second.panes.bars["console"].pin.isChecked(), "and it is still pinned"
    close(second)


def test_an_emptied_dock_stays_hidden_however_often_qt_shows_it(app, window):
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)

    dock = window.panes.docks["console"]
    for _ in range(3):
        dock.show()  # as Qt does while restoring a layout
        settle(app)
        assert not dock.isVisible()


# --- a pinned pane must not trap a dialog behind it -----------------------------------
def open_dialog(app, window, then):
    """Show a modal dialog the way a confirmation does, and act while it is up."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(
        QMessageBox.Warning, "Program?", "...", QMessageBox.Yes | QMessageBox.Cancel, window
    )
    QTimer.singleShot(50, lambda: (then(), box.accept()))
    box.exec()
    settle(app)


def test_a_pinned_detached_pane_stands_down_for_a_dialog(app, window, real_dialogs):
    """It was above everything, the dialog included.

    The dialog could not be read, and the window hiding it could not be moved
    either, because the dialog was holding the application: a lock-up with
    nothing on screen to explain it.
    """
    float_out(app, window.panes.docks["console"])
    window.panes.bars["console"].pin.setChecked(True)
    window.panes.detach("console")
    settle(app)
    detached = window.panes.detached["console"]
    on_top = lambda: bool(detached.windowFlags() & Qt.WindowStaysOnTopHint)  # noqa: E731
    assert on_top()

    seen = []
    open_dialog(app, window, lambda: seen.append(on_top()))
    assert seen == [False], "the dialog has to be reachable"
    assert on_top(), "and the pane goes back on top afterwards"
    assert detached.isVisible() and detached.pane.isVisible()


def test_a_pinned_floating_pane_stands_down_too(app, window, real_dialogs):
    dock = window.panes.docks["console"]
    float_out(app, dock)
    window.panes.bars["console"].pin.setChecked(True)
    settle(app)
    on_top = lambda: bool(dock.windowFlags() & Qt.WindowStaysOnTopHint)  # noqa: E731
    assert on_top()

    seen = []
    open_dialog(app, window, lambda: seen.append(on_top()))
    assert seen == [False]
    assert on_top()
    assert dock.widget().isVisible()


def test_an_unpinned_pane_is_left_alone_by_a_dialog(app, window, real_dialogs):
    float_out(app, window.panes.docks["console"])
    settle(app)
    before = window.panes.docks["console"].windowFlags()
    open_dialog(app, window, lambda: None)
    assert window.panes.docks["console"].windowFlags() == before, "nothing to stand down from"


# --- how big a detached window opens ----------------------------------------------------
def test_a_detached_pane_opens_big_enough_to_use(app, window):
    """It takes its size from the dock it came out of, and a dock that was
    never on screen has none worth having: the window came up a couple of
    hundred pixels across with the pane crushed into it."""
    window.panes.detach("console")

    out = window.panes.detached["console"]
    assert out.width() >= 600 and out.height() >= 400
    window.panes.attach("console")


def test_a_detached_window_comes_back_where_it_was_left(app, window):
    window.panes.detach("log")
    out = window.panes.detached["log"]
    out.setGeometry(QRect(140, 90, 980, 720))
    window.panes.save()
    window.panes.attach("log")

    window.panes.detach("log")

    again = window.panes.detached["log"].geometry()
    assert (again.width(), again.height()) == (980, 720)
    assert (again.x(), again.y()) == (140, 90), "on the monitor it was left on"
    window.panes.attach("log")


def test_a_hand_edited_size_that_makes_no_sense_is_ignored(app, window):
    window.ctx.settings.set("panes.detached_at.console", ["wide", "tall", 0, 0])

    window.panes.detach("console")

    assert window.panes.detached["console"].width() >= 600, "it falls back to a usable size"
    window.panes.attach("console")


def test_detached_windows_come_up_in_front_of_the_main_one(app, home, monkeypatch):
    """They were restored before the main window was shown, which then covered them."""
    from pyflashgui.ui.detached import DetachedPane

    first = restart(app)
    float_out(app, first.panes.docks["console"])
    first.panes.detach("console")
    settle(app)

    raised = []
    real = DetachedPane.raise_
    monkeypatch.setattr(DetachedPane, "raise_", lambda self: (raised.append(self), real(self)))
    second = restart(app, first, arrange=False)
    assert second.panes.detached["console"] in raised
    close(second)


# --- the View menu's own entries -------------------------------------------------------------
def test_a_pane_open_in_its_own_window_is_ticked_in_the_view_menu(app, window):
    """Its dock is hidden while it is out, so the dock's own action said it
    was closed while it was open in front of you."""
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)
    window._tick_view_menu()  # as opening the menu does
    assert window._view_actions["console"].isChecked()

    window.panes.detached["console"].close()
    settle(app)
    window._tick_view_menu()
    assert not window._view_actions["console"].isChecked()


def test_picking_an_open_detached_pane_brings_it_forward_and_leaves_it_open(app, window):
    """Behind the main window, or minimised: somebody reaching for the menu is
    looking for it, not trying to be rid of it."""
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)
    own = window.panes.detached["console"]
    own.showMinimized()
    settle(app)

    window._view_actions["console"].trigger()
    settle(app)
    assert window.panes.detached.get("console") is own, "still in its own window"
    assert not own.isHidden() and not own.isMinimized()
    assert window._view_actions["console"].isChecked()


def test_picking_a_docked_pane_puts_it_away_and_picking_it_again_brings_it_back(app, window):
    window.panes.show("log")
    settle(app)
    assert window.panes.on_screen("log")

    window._view_actions["log"].trigger()
    settle(app)
    assert not window.panes.on_screen("log") and not window._view_actions["log"].isChecked()

    window._view_actions["log"].trigger()
    settle(app)
    assert window.panes.on_screen("log") and window._view_actions["log"].isChecked()


def test_a_pane_closed_in_its_own_window_is_picked_back_into_one(app, window):
    float_out(app, window.panes.docks["console"])
    window.panes.detach("console")
    settle(app)
    window.panes.detached["console"].close()
    settle(app)

    window._view_actions["console"].trigger()
    settle(app)
    assert "console" in window.panes.detached
    assert window.panes.detached["console"].pane.isVisible(), "the pane, not a blank window"


# --- a pane that opens out of the window opens where it can be seen -----------------------------
def _wholly_on_a_screen(widget) -> bool:
    from PySide6.QtGui import QGuiApplication

    frame = widget.frameGeometry()
    return any(s.availableGeometry().contains(frame) for s in QGuiApplication.screens())


def test_a_window_above_the_top_of_the_screen_is_brought_down(app):
    from PySide6.QtWidgets import QWidget

    from pyflashgui.ui.panes import keep_in_view

    area = app.primaryScreen().availableGeometry()
    window = QWidget()
    window.setGeometry(area.left() + 40, area.top() - 60, 300, 200)
    window.show()
    app.processEvents()
    left = window.frameGeometry().left()
    assert keep_in_view(window) is True
    assert _wholly_on_a_screen(window)
    assert window.frameGeometry().left() == left, "moved no further than it had to be"
    assert window.width() == 300 and window.height() == 200
    window.close()


def test_a_window_already_in_view_is_left_where_it_is(app):
    from PySide6.QtWidgets import QWidget

    from pyflashgui.ui.panes import keep_in_view

    area = app.primaryScreen().availableGeometry()
    window = QWidget()
    window.setGeometry(area.left() + 50, area.top() + 50, 300, 200)
    window.show()
    app.processEvents()
    before = window.geometry()
    assert keep_in_view(window) is False
    assert window.geometry() == before
    window.close()


def test_a_window_bigger_than_the_screen_is_made_to_fit(app):
    from PySide6.QtWidgets import QWidget

    from pyflashgui.ui.panes import keep_in_view

    area = app.primaryScreen().availableGeometry()
    window = QWidget()
    window.setGeometry(area.left() - 100, area.top() - 100, area.width() + 400, area.height() + 400)
    window.show()
    app.processEvents()
    assert keep_in_view(window) is True
    assert _wholly_on_a_screen(window)
    window.close()


def test_a_floating_pane_shown_off_the_top_comes_into_view(app, window):
    area = app.primaryScreen().availableGeometry()
    dock = window.panes.docks["log"]
    dock.hide()
    dock.setFloating(True)
    dock.setGeometry(QRect(area.left() + 30, area.top() - 80, 320, 240))
    window.panes.show("log")
    settle(app)
    assert dock.isFloating() and dock.isVisible()
    assert _wholly_on_a_screen(dock)


def test_a_detached_pane_remembered_off_the_screen_comes_into_view(app, window):
    area = app.primaryScreen().availableGeometry()
    # As left on a monitor that is no longer there.
    window.ctx.settings.set(
        "panes.detached_at.log", [area.right() + 3000, area.top() - 500, 400, 300]
    )
    window.panes.detach("log")
    settle(app)
    assert _wholly_on_a_screen(window.panes.detached["log"])
    window.panes.attach("log")
