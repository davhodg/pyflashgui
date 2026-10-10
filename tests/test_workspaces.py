# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""One workspace per product, and one called default nobody has to meet.

Somebody who never asked for workspaces must not be able to tell that they
were built: there is a ``default`` one, made silently, and everything is kept
in it.
"""

import json
import shutil

import pytest
from PySide6.QtCore import QSettings

from pyflashgui.core import paths, workspaces
from pyflashgui.core.context import Context
from pyflashgui.core.layout import Layout


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    return tmp_path


def test_a_fresh_install_just_gets_a_default(home):
    assert workspaces.active() == workspaces.DEFAULT
    assert workspaces.names() == [workspaces.DEFAULT]
    assert workspaces.dir_for(workspaces.DEFAULT).is_dir()


# --- which one is in use -------------------------------------------------------------------
def test_default_when_nothing_says_otherwise(home):
    assert workspaces.active() == workspaces.DEFAULT


def test_the_choice_is_remembered(home):
    workspaces.create("Pump controller")
    workspaces.set_active("Pump controller")
    assert workspaces.active() == "Pump controller"


def test_a_pointer_to_a_workspace_that_is_gone_falls_back(home):
    """Deleted by hand, or a file typed wrong: still a working tool."""
    workspaces.create("gone")
    workspaces.set_active("gone")
    shutil.rmtree(workspaces.dir_for("gone"))  # somebody tidying up in Explorer
    assert workspaces.active() == workspaces.DEFAULT


def test_a_damaged_pointer_falls_back_too(home):
    workspaces._ensure()
    (home / workspaces.POINTER).write_text("not json at all", encoding="utf-8")
    assert workspaces.active() == workspaces.DEFAULT


def test_default_is_listed_first(home):
    for name in ("zebra", "alpha"):
        workspaces.create(name)
    assert workspaces.names() == [workspaces.DEFAULT, "alpha", "zebra"]


# --- naming one ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["Pump controller", "drive-2", "rev_1.4", "A"])
def test_names_people_would_type(home, name):
    assert workspaces.why_not(name) == ""


@pytest.mark.parametrize(
    "name, because",
    [
        ("", "needs a name"),
        ("   ", "needs a name"),
        ("../escape", "folder name"),
        ("drive/2", "folder name"),
        (".hidden", "folder name"),
        ("con", "Windows"),
        ("LPT1", "Windows"),
        ("x" * 65, "at most"),
    ],
)
def test_names_that_would_not_survive_being_a_folder(home, name, because):
    """A reason rather than a silent tidy-up: they typed it, so tell them."""
    assert because in workspaces.why_not(name)


def test_the_space_around_a_typed_name_is_not_part_of_it(home):
    """Nobody types a trailing space on purpose, and a folder called
    "drive " is one that cannot be found again."""
    assert workspaces.why_not(" drive ") == ""
    workspaces.create(" drive ")
    assert workspaces.exists("drive")


def test_a_name_already_taken_is_refused(home):
    workspaces.create("drive")
    assert "already a workspace" in workspaces.why_not("drive")


def test_creating_a_bad_name_raises_rather_than_making_a_mess(home):
    with pytest.raises(ValueError):
        workspaces.create("../escape")


# --- making, renaming, removing ---------------------------------------------------------------
def filled_default():
    """The default workspace with settings and a file of its own in it."""
    workspaces._ensure()
    default = workspaces.dir_for(workspaces.DEFAULT)
    (default / "settings.json").write_text('{"flash.files": ["a.hex"]}', encoding="utf-8")
    (default / "notes").mkdir(exist_ok=True)
    (default / "notes" / "mine.txt").write_text("# mine\n", encoding="utf-8")


def test_save_as_keeps_what_was_on_screen(home):
    """Somebody asking for it means "keep this and call it something else"."""
    filled_default()
    workspaces.create("Pump controller", copy_from=workspaces.DEFAULT)
    forked = workspaces.dir_for("Pump controller")
    assert json.loads((forked / "settings.json").read_text())["flash.files"] == ["a.hex"]
    assert (forked / "notes" / "mine.txt").exists()


def test_a_fork_is_a_copy_and_not_a_share(home):
    filled_default()
    workspaces.create("other", copy_from=workspaces.DEFAULT)
    (workspaces.dir_for("other") / "settings.json").write_text("{}", encoding="utf-8")
    default = workspaces.dir_for(workspaces.DEFAULT)
    assert json.loads((default / "settings.json").read_text())["flash.files"] == ["a.hex"]


def test_renaming_takes_the_pointer_with_it(home):
    workspaces.create("old name")
    workspaces.set_active("old name")
    workspaces.rename("old name", "new name")
    assert workspaces.active() == "new name"
    assert not workspaces.exists("old name")


def test_the_default_cannot_be_renamed_or_deleted(home):
    """It is the one that is always there, and something has to be."""
    with pytest.raises(ValueError):
        workspaces.rename(workspaces.DEFAULT, "something else")
    with pytest.raises(ValueError):
        workspaces.delete(workspaces.DEFAULT)


def test_the_one_in_use_cannot_be_deleted(home):
    """Pulling the settings out from under a running window is the worse answer."""
    workspaces.create("drive")
    workspaces.set_active("drive")
    with pytest.raises(ValueError, match="Switch to another one first"):
        workspaces.delete("drive")


def test_deleting_takes_the_folder_with_it(home):
    workspaces.create("scrap")
    workspaces.delete("scrap")
    assert not workspaces.exists("scrap")
    assert "scrap" not in workspaces.names()


# --- what belongs to which -------------------------------------------------------------------
def test_the_layout_lives_in_the_workspace_folder(home):
    """So that a workspace is one thing that can be copied or sent on. In
    QSettings it would be the one part of it that could not travel."""
    ctx = Context()
    ctx.layout.set("window", b"\x01\x02\x03")
    assert (ctx.workspace_dir / "layout.json").exists()
    assert Layout(ctx.workspace_dir / "layout.json").get("window") == b"\x01\x02\x03"


def test_an_empty_layout_is_nothing_rather_than_empty_bytes(home):
    """Qt answers restoreState(b"") by leaving the window with no docks."""
    ctx = Context()
    assert ctx.layout.get("window") is None
    ctx.layout.set("window", b"")
    assert ctx.layout.get("window") is None


def test_a_damaged_layout_file_is_no_layout_rather_than_a_crash(home):
    ctx = Context()
    (ctx.workspace_dir / "layout.json").write_text("{ truncated", encoding="utf-8")
    assert Layout(ctx.workspace_dir / "layout.json").get("window") is None


def test_the_user_folder_itself_is_still_the_user_folder(home):
    """Recordings, A2Ls and the scripts people keep there are not disturbed."""
    (home / "capture.blf").write_text("x", encoding="utf-8")
    workspaces._ensure()
    assert (home / "capture.blf").exists()
    assert paths.user_dir() == home


# --- and the window that opens on it -----------------------------------------------------------
# --- the menu, the title and the switch ----------------------------------------------------
@pytest.fixture
def window(app, home):
    from pyflashgui.ui.main_window import MainWindow

    QSettings().clear()
    win = MainWindow()
    win.show()
    app.processEvents()
    yield win
    win.close()


def switch_menu(window):
    """The Switch to submenu, rebuilt as opening the menu would rebuild it."""
    window.workspace_menu._build()
    return window.workspace_menu.menu.actions()[1].menu()


def test_the_title_names_a_workspace_that_is_not_the_default(app, home):
    from pyflashgui.ui.main_window import MainWindow

    workspaces.create("Pump controller")
    workspaces.set_active("Pump controller")
    win = MainWindow()
    assert win.windowTitle().endswith(" - Pump controller")
    win.close()


def test_what_a_switch_actually_does(app, home):
    """The window is replaced rather than persuaded: the settings, the hooks
    and the layout are all read once, while it is being built."""
    from pyflashgui.ui.main_window import MainWindow
    from pyflashgui.ui.session import Session

    QSettings().clear()
    session = Session(MainWindow)
    first = session.open()
    first.ctx.settings.set("flash.files", ["first.hex"])
    workspaces.create("second")

    second = session.reopen("second")
    assert second is not first
    assert not first.isVisible(), "the one that asked is the one that goes"
    assert second.ctx.workspace == "second"
    assert second.ctx.settings.get("flash.files") is None, "a workspace of its own"
    assert second.windowTitle().endswith(" - second")

    back = session.reopen(workspaces.DEFAULT)
    assert back.ctx.settings.get("flash.files") == ["first.hex"], "and the first is as it was"
    back.close()


def test_asking_the_window_to_switch_reaches_the_session(app, home):
    """The signal is the whole of the connection between the two."""
    from pyflashgui.ui.main_window import MainWindow
    from pyflashgui.ui.session import Session

    QSettings().clear()
    session = Session(MainWindow)
    first = session.open()
    workspaces.create("drive")

    first.reopen_requested.emit("drive")
    app.processEvents()
    assert session.window is not first
    assert session.window.ctx.workspace == "drive"
    assert workspaces.active() == "drive", "and the choice is remembered"
    session.window.close()


def test_switching_to_a_workspace_that_is_not_there_stays_put(app, home):
    from pyflashgui.ui.main_window import MainWindow
    from pyflashgui.ui.session import Session

    QSettings().clear()
    session = Session(MainWindow)
    session.open()
    session.reopen("never made")
    assert session.window.ctx.workspace == workspaces.DEFAULT
    session.window.close()


# --- managing them ----------------------------------------------------------------------------
def test_a_folder_is_made_once_and_left_alone_after(tmp_path, monkeypatch):
    """Making a directory is the expensive call on a watched or redirected
    profile, so it is asked about first; the folder still has to appear."""
    from pyflashgui.core import paths

    wanted = tmp_path / "deep" / "folder"
    assert paths.made(wanted).is_dir(), "it makes what is not there, parents and all"

    made = []
    monkeypatch.setattr(type(wanted), "mkdir", lambda self, **k: made.append(self))
    assert paths.made(wanted) == wanted
    assert made == [], "and does not ask the file system to make it again"
