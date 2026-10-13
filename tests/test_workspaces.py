# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""One workspace per product, and one called default nobody has to meet.

Somebody who never asked for workspaces must not be able to tell that they
were built: there is a ``default`` one, made silently, and everything is kept
in it.
"""

import json
import shutil
import time

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from pyflashgui import APP_NAME, __version__
from pyflashgui.core import paths, workspaces
from pyflashgui.core.context import Context
from pyflashgui.core.layout import Layout
from pyflashgui.ui import files_view, messages


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
    return next(a.menu() for a in window.workspace_menu.menu.actions() if a.menu())


def test_a_single_product_never_meets_the_word(window):
    """The title says nothing while the workspace is the one everybody has."""
    assert window.windowTitle() == f"{APP_NAME} {__version__}"
    assert [a.text() for a in switch_menu(window).actions()] == [workspaces.DEFAULT]


def test_the_workspace_menu_is_in_the_file_menu_above_exit(window):
    file_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&File")
    texts = [a.text() for a in file_menu.actions() if not a.isSeparator()]
    assert texts == ["Workspace", "Exit"]
    inside = [a.text() for a in window.workspace_menu.menu.actions()]
    assert inside == ["New...", "Save as...", "Switch to", "Manage...", "", "Open folder"]


def test_switch_to_lists_them_all_and_ticks_the_one_in_use(window):
    workspaces.create("board")
    actions = switch_menu(window).actions()
    assert [a.text() for a in actions] == [workspaces.DEFAULT, "board"]
    assert [a.isChecked() for a in actions] == [True, False]


def test_new_on_the_menu_makes_an_empty_one_and_asks_to_open_it(window, monkeypatch):
    window.ctx.settings.set(files_view.FILES_KEY, [{"path": "app.hex", "enabled": True}])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Test rig", True))
    asked: list[str] = []
    window.workspace_menu.switch_requested.connect(asked.append)

    window.workspace_menu.menu.aboutToShow.emit()  # it is rebuilt each time it opens
    assert window.workspace_menu.new_action in window.workspace_menu.menu.actions()
    window.workspace_menu.new_action.trigger()

    assert asked == ["Test rig"]
    made = workspaces.dir_for("Test rig") / "settings.json"
    assert not made.exists() or files_view.FILES_KEY not in json.loads(made.read_text())


def test_save_as_forks_what_is_on_screen_and_asks_to_open_it(window, monkeypatch):
    window.ctx.settings.set(files_view.FILES_KEY, [{"path": "app.hex", "enabled": True}])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Pump controller", True))
    asked: list[str] = []
    window.workspace_menu.switch_requested.connect(asked.append)

    window.workspace_menu._save_as()

    assert asked == ["Pump controller"], "and switching to it is somebody else's job"
    forked = workspaces.dir_for("Pump controller") / "settings.json"
    assert json.loads(forked.read_text())[files_view.FILES_KEY][0]["path"] == "app.hex"


def test_save_as_with_a_name_that_will_not_do_makes_nothing(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("../escape", True))
    said: list[str] = []
    monkeypatch.setattr(messages, "warning", lambda _p, _t, text, *a, **k: said.append(text))
    asked: list[str] = []
    window.workspace_menu.switch_requested.connect(asked.append)

    window.workspace_menu._save_as()

    assert asked == []
    assert said and "folder name" in said[0], "told why, rather than quietly repaired"
    assert workspaces.names() == [workspaces.DEFAULT]


def test_cancelling_save_as_does_nothing(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("board", False))
    window.workspace_menu._save_as()
    assert workspaces.names() == [workspaces.DEFAULT]


def test_switching_to_the_one_you_are_in_does_nothing(window):
    asked: list[str] = []
    window.reopen_requested.connect(asked.append)
    window._switch_workspace(workspaces.DEFAULT)
    assert asked == []


def test_switching_with_nothing_connected_does_not_ask(window, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "exec", lambda *a, **k: pytest.fail("nothing to lose, nothing to ask")
    )
    workspaces.create("board")
    asked: list[str] = []
    window.reopen_requested.connect(asked.append)
    window._switch_workspace("board")
    assert asked == ["board"]


def connect_simulated(window, app) -> None:
    """Connect the window to the simulated probe, as pressing Connect would."""
    window.flasher.set_backend("simulated")
    window.flasher.connect_to("SIM0001", "sim_single")
    deadline = time.monotonic() + 5
    while not window.flasher.connected and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert window.flasher.connected


def test_switching_away_from_a_connected_target_asks_first(window, app, monkeypatch):
    """A workspace holds which probe and which target, so opening another one
    lets go of the target this one is connected to."""
    connect_simulated(window, app)
    # Asked of the simulated target too: the question is about the switch.
    workspaces.create("board")
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda box: (seen.append(box.text() + " " + box.informativeText()), QMessageBox.Cancel)[1],
    )
    asked: list[str] = []
    window.reopen_requested.connect(asked.append)

    window._switch_workspace("board")
    assert asked == [], "cancelled means stay"
    assert seen and "sim_single is connected" in seen[0] and "Open board anyway?" in seen[0]

    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Yes)
    window._switch_workspace("board")
    assert asked == ["board"]


def test_agreeing_once_covers_the_session(window, app, monkeypatch):
    connect_simulated(window, app)
    workspaces.create("board")
    workspaces.create("other")
    times: list[int] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: (times.append(1), QMessageBox.Yes)[1])
    window._switch_workspace("board")
    window._switch_workspace("other")
    assert len(times) == 1, "it is the same loss each time"


def test_choosing_another_on_the_menu_opens_it(app, home):
    """The whole way through: the menu, the window, and the session that swaps them."""
    from pyflashgui.ui.main_window import MainWindow
    from pyflashgui.ui.session import Session

    QSettings().clear()
    workspaces.create("board")
    session = Session(MainWindow)
    first = session.open()
    first.workspace_menu._switch("board")
    app.processEvents()
    assert session.window is not first
    assert session.window.ctx.workspace == "board"
    assert session.window.windowTitle().endswith(" - board")
    assert workspaces.active() == "board", "and it is the one opened next time"
    session.window.close()


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
def rows_of(dialog) -> dict[str, int]:
    return {dialog.list.item(i).data(Qt.UserRole): i for i in range(dialog.list.count())}


def test_manage_will_not_offer_to_remove_the_ground_you_stand_on(app, home):
    from pyflashgui.ui.workspace_menu import ManageWorkspaces

    workspaces.create("board")
    workspaces.create("spare")
    dialog = ManageWorkspaces(None, current="board")
    rows = rows_of(dialog)
    for name, enabled, why in (
        (workspaces.DEFAULT, False, "always there"),
        ("board", False, "Switch to another one first"),
        ("spare", True, ""),
    ):
        dialog.list.setCurrentRow(rows[name])
        assert dialog.delete.isEnabled() == enabled, name
        assert dialog.rename.isEnabled() == enabled, name
        assert why in dialog.rename.toolTip()
    dialog.deleteLater()


def test_manage_deletes_one_that_is_not_in_use(app, home, monkeypatch):
    from pyflashgui.ui.workspace_menu import ManageWorkspaces

    workspaces.create("scrap")
    dialog = ManageWorkspaces(None, current=workspaces.DEFAULT)
    dialog.list.setCurrentRow(rows_of(dialog)["scrap"])
    monkeypatch.setattr(messages, "warning", lambda *a, **k: QMessageBox.Cancel)
    dialog._delete()
    assert workspaces.exists("scrap"), "Cancel keeps it"
    monkeypatch.setattr(messages, "warning", lambda *a, **k: QMessageBox.Yes)
    dialog._delete()
    assert not workspaces.exists("scrap")
    dialog.deleteLater()


def test_manage_renames_and_the_list_follows(app, home, monkeypatch):
    from pyflashgui.ui.workspace_menu import ManageWorkspaces

    workspaces.create("old")
    dialog = ManageWorkspaces(None, current=workspaces.DEFAULT)
    dialog.list.setCurrentRow(rows_of(dialog)["old"])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("new", True))
    dialog._rename()
    assert workspaces.exists("new") and not workspaces.exists("old")
    assert "new" in rows_of(dialog)
    dialog.deleteLater()


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
