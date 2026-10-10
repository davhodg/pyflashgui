# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Nothing said to the user is lost because a pane was closed.

The Event Log is a pane like any other and can be shut. Without a level on
each line, shutting it would mean "throw away anything you were going to tell
me": press a button that cannot do its job, and it would appear to do nothing
at all.
"""

import pytest
from PySide6.QtCore import QSettings

from pyflashgui.core.events import ERROR, INFORMATION, WARNING, EventLog
from pyflashgui.ui.main_window import MainWindow


def settle(app, times=5):
    for _ in range(times):
        app.processEvents()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    QSettings().clear()
    win = MainWindow()
    win.show()
    # Settled, not a single turn: the pane is shown a turn of the event loop
    # after a problem, so anything the platform said while the window was
    # being built has to land before a test starts closing things. Otherwise
    # a Qt critical from a plugin reopens the pane in the middle of a test
    # about whether notes reopen it.
    settle(app)
    yield win
    win.close()


# --- the levels themselves ------------------------------------------------------------
def test_a_level_reaches_whoever_is_listening(app):
    events = EventLog()
    seen = []
    events.posted.connect(lambda message, level: seen.append((message, level)))

    events.information("a note")
    events.warning("did not happen")
    events.error("went wrong")
    assert seen == [("a note", INFORMATION), ("did not happen", WARNING), ("went wrong", ERROR)]


def test_a_level_nobody_recognises_is_only_a_note(app):
    """A typo in somebody's hook must not be able to make the pane spring open."""
    events = EventLog()
    seen = []
    events.posted.connect(lambda message, level: seen.append(level))
    events.post("hello", "URGENT!!")
    assert seen == [INFORMATION], "and the message still arrives"


# --- the pane -------------------------------------------------------------------------
def test_a_note_does_not_reopen_a_closed_log(app, window):
    """Closing it has to keep meaning "stop chattering at me"."""
    dock = window.panes.docks["log"]
    dock.close()
    settle(app)
    assert not dock.isVisible()

    window.events.information("something happened")
    settle(app)
    assert not dock.isVisible()
    assert "something happened" in window.log.toPlainText(), "recorded even so"


@pytest.mark.parametrize("level", (WARNING, ERROR))
def test_a_problem_opens_it(app, window, level):
    dock = window.panes.docks["log"]
    dock.close()
    settle(app)

    window.events.post("that did not work", level)
    settle(app)
    assert dock.isVisible(), f"a {level} with nowhere to appear is a button that does nothing"
    assert "that did not work" in window.log.toPlainText()


def test_a_burst_of_problems_opens_it_once(app, window):
    """Ticking Cyclic on a selection with no bus is one warning per row."""
    dock = window.panes.docks["log"]
    dock.close()
    settle(app)
    for row in range(20):
        window.events.warning(f"row {row}: no bus")
    assert window._surfacing, "still pending, so twenty warnings cost one show"
    settle(app)
    assert dock.isVisible()
    assert not window._surfacing


def test_a_problem_while_the_window_is_still_opening_is_not_lost(app, tmp_path, monkeypatch):
    """The saved layout is restored during __init__, after such a warning.

    Showing the pane there and then would simply be undone by it, which is
    why the show waits for the event loop.
    """
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    QSettings().clear()
    first = MainWindow()
    first.show()
    settle(app)
    first.panes.docks["log"].close()
    settle(app)
    first.close()  # saves a layout with the Event Log hidden

    second = MainWindow()
    second.show()
    settle(app)
    assert not second.panes.docks["log"].isVisible(), "the saved layout is honoured"
    second.events.warning("a problem at startup")
    settle(app)
    assert second.panes.docks["log"].isVisible()
    second.close()


def test_the_pane_is_written_to_in_one_place(app, window):
    """Which is what made colouring the levels a change there and nowhere
    else. Worth keeping: a second writer would be a line with no level, and
    so a line that cannot be coloured or open the pane."""
    import inspect

    from pyflashgui.ui import main_window

    source = inspect.getsource(main_window)
    assert source.count("cursor.insertText") == 1
    assert "self.log.appendPlainText" not in source, "text with no level, and no format"


# --- what now says it properly --------------------------------------------------------
# --- how much a line matters, and what it looks like ------------------------------------
def test_each_level_that_matters_has_its_own_colour(app):
    """A log where every line looks the same is a log nobody reads: the
    encoder fault arrives in the same grey as the plugin that loaded."""
    from pyflashgui.core.events import ERROR, GOOD, INFORMATION, WARNING
    from pyflashgui.ui import event_colours

    for dark in (False, True):
        shown = {level: event_colours.colour_for(level, dark) for level in (ERROR, WARNING, GOOD)}
        assert all(colour is not None for colour in shown.values())
        assert len({colour.name() for colour in shown.values()}) == 3, "told apart at a glance"
        assert event_colours.colour_for(INFORMATION, dark) is None, "the ordinary line is plain"

    assert event_colours.bold_for(ERROR)
    assert not event_colours.bold_for(WARNING), "or the errors have nothing to stand out from"


def test_the_colours_follow_the_background_they_are_read_against(app):
    """A red dark enough for white disappears into a dark theme."""
    from PySide6.QtGui import QColor, QPalette

    from pyflashgui.core.events import ERROR
    from pyflashgui.ui import event_colours

    assert event_colours.colour_for(ERROR, True) != event_colours.colour_for(ERROR, False)
    assert (
        event_colours.colour_for(ERROR, True).lightness()
        > event_colours.colour_for(ERROR, False).lightness()
    ), "the dark theme's is the lighter one"

    pale, dim = QPalette(), QPalette()
    pale.setColor(QPalette.Base, QColor("#ffffff"))
    dim.setColor(QPalette.Base, QColor("#1e1e1e"))
    assert not event_colours.dark_behind(pale)
    assert event_colours.dark_behind(dim)


def shape_of(window, line: int):
    """How the Event Log drew a line: its colour (None if plain) and weight."""
    from PySide6.QtGui import QTextFormat

    block = window.log.document().findBlockByNumber(line)
    fmt = next(iter(block.begin())).fragment().charFormat()
    coloured = fmt.hasProperty(QTextFormat.ForegroundBrush)
    return (fmt.foreground().color().name() if coloured else None), fmt.fontWeight()


def colour_of(window, line: int):
    return shape_of(window, line)[0]


def test_an_error_is_drawn_in_its_own_colour_and_a_note_is_not(app, window):
    from pyflashgui.core.events import ERROR, GOOD, WARNING
    from pyflashgui.ui import event_colours

    window.log.clear()
    window.events.information("CAN 1 connected")
    window.events.error("EMCY node 1: 0x5000 Device hardware")
    window.events.warning("Node 1: identify failed")
    window.events.good("EMCY node 1: 0x0000 Error reset or no error")
    settle(app)

    dark = window._dark_log()
    assert colour_of(window, 0) is None, "an ordinary line is left as the theme has it"
    assert colour_of(window, 1) == event_colours.colour_for(ERROR, dark).name()
    assert colour_of(window, 2) == event_colours.colour_for(WARNING, dark).name()
    assert colour_of(window, 3) == event_colours.colour_for(GOOD, dark).name()
    assert "CAN 1 connected" in window.log.toPlainText(), "and the text is still the text"

    from PySide6.QtGui import QFont

    assert shape_of(window, 1)[1] == QFont.Bold, "an error is the one to find while scrolling"
    assert shape_of(window, 2)[1] != QFont.Bold


def test_a_traceback_keeps_its_shape(app, window):
    """Written as text rather than as HTML, so the indentation survives and
    nothing in a device's own message is read as markup."""
    window.log.clear()
    window.events.error('Traceback:\n    File "x.py", line 1\n        raise ValueError("<b>")')
    settle(app)
    shown = window.log.toPlainText()
    assert '    File "x.py", line 1' in shown
    assert "<b>" in shown, "not swallowed as a tag"


def test_good_news_does_not_open_the_pane(app, window):
    """A fault clearing is worth seeing in green; it is not worth a pane
    springing open over."""
    from pyflashgui.core.events import GOOD, PROBLEMS

    assert GOOD not in PROBLEMS


# --- what a library line says when it reaches the log -----------------------------------
def test_the_event_log_keeps_everything_until_cleared(app, window):
    """The line that matters is often the first of a thousand."""
    assert window.log.maximumBlockCount() == 0, "no limit"
    for n in range(2500):
        window.events.post(f"line {n}", INFORMATION)
    app.processEvents()
    assert window.log.document().blockCount() >= 2500
    clear = next(a for a in window.log_menu().actions() if a.text() == "Clear")
    clear.trigger()
    assert window.log.document().isEmpty()
