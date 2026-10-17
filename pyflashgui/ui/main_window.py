# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Main window: the probe bar, dockable panes, persistent layout."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QFont,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QStatusBar,
    QTabBar,
    QWidget,
)

from pyflashgui import APP_NAME, __version__
from pyflashgui.backends import jlink_backend
from pyflashgui.backends.base import TargetInfo
from pyflashgui.core import shortcut, timing, workspaces
from pyflashgui.core.context import Context
from pyflashgui.core.events import PROBLEMS, EventLog
from pyflashgui.core.excepthook import ExceptionLogger
from pyflashgui.core.flasher import Flasher, size_text
from pyflashgui.core.memory_map import FLASH, RAM, Region
from pyflashgui.core.pack_manager import PackManager
from pyflashgui.ui import event_colours, folders, messages, theme
from pyflashgui.ui.confirm import Confirmations, Remembered
from pyflashgui.ui.console_view import ConsoleView
from pyflashgui.ui.files_view import Entry, FilesView
from pyflashgui.ui.help_menu import HelpMenu
from pyflashgui.ui.map_view import MapView
from pyflashgui.ui.memory_view import MemoryView
from pyflashgui.ui.packs_dialog import PacksDialog
from pyflashgui.ui.panes import PaneKind, Panes
from pyflashgui.ui.probe_bar import ProbeBar
from pyflashgui.ui.read_dialog import ReadDialog
from pyflashgui.ui.scripting import Flash, namespace
from pyflashgui.ui.scripts_menu import ScriptsMenu
from pyflashgui.ui.workspace_menu import SWITCH_WHILE_CONNECTED, WorkspaceMenu


def window_title() -> str:
    """The workspace is named only when it is not the one everybody has.

    Somebody with a single product should not be able to tell from the window
    that workspaces were built, and a title bar reading "default" would be the
    one place that gave it away.
    """
    name = workspaces.active()
    return f"{APP_NAME} {__version__}" + ("" if name == workspaces.DEFAULT else f" - {name}")


# Bumped whenever the set of docks changes. restoreState declines a state
# saved under a different version, so an old layout is replaced by the current
# default instead of being restored with panes missing.
LAYOUT_VERSION = 6

#: Open on a first run. Everything else is one click away in the View menu.
DEFAULT_VISIBLE = ("files", "log")

#: In the place the Memory panes take, while there are none there.
MEMORY_SPACE_TEXT = (
    "Double-click a file or a read in Files, or Read... from the target, "
    "and its bytes are shown here."
)

#: What a Memory pane opens at, when it opens in front of the window:
#: wide enough for an address, sixteen bytes and their text.
MEMORY_PANE_SIZE = (760, 560)
#: The console is typed into, so it wants the width of a line of Python
#: and room for what a script prints.
CONSOLE_PANE_SIZE = (820, 480)

#: How near the bottom of the Event Log still counts as being at the bottom,
#: in scrollbar steps. Exactly at the end is too strict: a line arriving
#: while the last one is part-scrolled would then stop following.
AT_END = 4

#: What the window opens at, and what Reset layout puts it back to.
DEFAULT_WIDTH = 1100
#: In QSettings, not the workspace: whether this person has been told, on
#: this machine, where a shortcut is made.
SHORTCUT_TOLD_KEY = "shortcut/told"
#: Where J-Link Commander is, when it is not where it is looked for.
COMMANDER_SETTING = "jlink/commander"
DEFAULT_HEIGHT = 720


def describe_device(target: str, info: TargetInfo | None, regions: list[Region]) -> str:
    """A line about a target: its maker, its core, and its flash and RAM.

    Only what is known. A target with nothing known of it gets no line,
    rather than a row of dashes.
    """
    parts = [part for part in (info.vendor, info.core) if part] if info else []
    for kind, label in ((FLASH, "flash"), (RAM, "RAM")):
        total = sum(r.length for r in regions if r.kind == kind and not r.alias_of)
        if total:
            parts.append(f"{label} {size_text(total)}")
    return f"{target}: " + " | ".join(parts) if target and parts else ""


class MainWindow(QMainWindow):
    #: Open this workspace instead. Emitted rather than acted on, because a
    #: switch is a full reload and the window that asks is the one that goes:
    #: something outside it has to close it and open the next.
    reopen_requested = Signal(str)
    #: The window is going. Emitted before anything is torn down, because
    #: something that has left a target in a state needs one last chance to
    #: take it back.
    closing = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(window_title())
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.setDockNestingEnabled(True)  # full grid layouts, not just the four edges

        # --- log pane first: everything else reports into it -----------------
        #: True from the moment the window starts closing, so that what is
        #: torn down on the way out is not reported as if somebody did it.
        self._closing = False
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        # Everything is kept, however long the session: the line that matters
        # is often the first of a thousand, and a log that drops its oldest
        # lines drops exactly that one. Clear, on the right-click, empties it.
        self.log.setMaximumBlockCount(0)
        self.log.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log.customContextMenuRequested.connect(self._log_menu)
        #: Every line said to the user arrives here with a level, and this is
        #: the only thing that writes to the pane. Warnings and errors open it
        #: if it has been closed; notes do not.
        self.events = EventLog()
        self._surfacing = False
        self.events.posted.connect(self._on_event)

        self.ctx = Context(events=self.events)
        #: Started with pythonw, which has no console, so a traceback from a
        #: Qt slot would otherwise go nowhere at all -- see the module.
        self.exceptions = ExceptionLogger(self.events.post)
        self.exceptions.install()
        timing.mark("exception hook")

        #: Shared, so that agreeing once covers erasing and programming a
        #: target rather than each asking again.
        self.confirm = Confirmations(Remembered())
        # Before anything asks a backend for its probes: where Commander
        # is belongs to this machine, so it is kept with the window's place
        # on the screen and not in the workspace.
        jlink_backend.set_commander(str(QSettings().value(COMMANDER_SETTING, "") or ""))
        #: The one thing that talks to a probe. The bar and the panes ask
        #: it for things and listen for what comes back.
        self.flasher = Flasher(self.events, parent=self)
        #: The CMSIS-Packs pyOCD gets most of its targets from. A new one
        #: is a new set of targets, whichever backend is chosen just now.
        self.packs = PackManager(self.events, parent=self)
        self.packs.changed.connect(self.flasher.refresh_targets)
        #: The probe and the target, for the Python console and its scripts.
        self.flash = Flash(self)

        # --- toolbar ---------------------------------------------------------
        self.probe_bar = ProbeBar(self.flasher, self.ctx)
        self.addToolBar(self.probe_bar)

        # --- panes -----------------------------------------------------------
        #: Every dock, and how many of each kind there can be. The window
        #: names a pane to open it and then leaves it alone.
        self.panes = Panes(self, self.ctx)
        self._register_panes()
        # Opened in the order the View menu should list them: what is open
        # and done with it, and what the tool has to say for itself.
        self.files_view = self.panes.view(self.panes.add("files"))
        self.panes.add("log")
        # Made now and hidden, so that the View menu has it: the menu lists
        # the panes there are.
        self.console = self.panes.view(self.panes.add("console", show=False))
        #: Where the Memory panes go, kept for them while there are none, so
        #: that the Files pane does not take the whole width and then give
        #: half of it back the moment something is shown. Not a pane: it
        #: cannot be moved or closed, and is not in the View menu.
        self.memory_space = self._make_memory_space()
        #: How wide the Files pane was beside the Memory panes. See eventFilter.
        self._files_width = 0
        self.panes.docks["files"].installEventFilter(self)
        self._arrange_default()
        # The map is of what is ticked on the chosen target, so either
        # changing redraws it.
        #: What is known of the chosen target, for the status bar: who makes
        #: it, its core, how much flash and RAM it has. Made here, before
        #: the map is first drawn, which is what fills it in.
        self.device_label = QLabel()
        #: The targets the backend last listed, by name in capitals.
        self._targets: dict[str, TargetInfo] = {}
        self.flasher.targets_changed.connect(self._on_targets)
        self.files_view.changed.connect(self._on_files_changed)
        self.files_view.read_requested.connect(self._read_memory)
        self.files_view.opened.connect(self._open_memory)
        self.files_view.removed.connect(self._close_memory)
        self.files_view.compare_requested.connect(self._compare)
        self.flasher.regions_changed.connect(self._refresh_map)
        self._refresh_map()
        # A pane for each file the workspace came with, before the saved
        # arrangement is restored, so that it has them to put where they were.
        for entry in self.files_view.entries:
            if entry.image is not None:
                self._open_memory(entry, in_window_only=True)
        if names := self._memory_panes():
            self.panes.docks[names[0]].raise_()

        self.setStatusBar(QStatusBar())
        self.statusBar().addWidget(self.device_label, 1)
        timing.mark("panes built")

        # --- menus & layout persistence --------------------------------------
        file_menu = self.menuBar().addMenu("&File")
        file_menu.setToolTipsVisible(True)
        #: Run script... and the last few run, in the Python Console.
        self.scripts_menu = ScriptsMenu(self, self.ctx)
        self.scripts_menu.install(file_menu)
        self.scripts_menu.run_wanted.connect(self.run_script_in_console)
        self.console.ran.connect(self.scripts_menu.remember)
        file_menu.addSeparator()
        #: One workspace per product: new, save as, switch to and manage.
        self.workspace_menu = WorkspaceMenu(self, self.ctx)
        self.workspace_menu.install(file_menu)
        self.workspace_menu.switch_requested.connect(self._switch_workspace)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Exit", self.close)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.setShortcut(QKeySequence.Quit)

        #: One action in two menus. The View menu is where you reach for it
        #: while arranging panes; Tools > Reset is where you reach for it
        #: when putting things back. Parented to the window rather than to
        #: either menu, because the View menu is rebuilt and clear() deletes
        #: the actions a menu owns.
        self.reset_layout_action = QAction("Reset layout", self)
        self.reset_layout_action.setToolTip(
            "Put every pane back where it starts, hide the ones that start\n"
            "hidden, and put the window back to the size it opens at.\n"
            "Nothing else is touched."
        )
        self.reset_layout_action.triggered.connect(self._reset_layout)
        self.view_menu = self.menuBar().addMenu("&View")
        #: Pane name -> its entry in the View menu. See ``_pane_action``.
        self._view_actions: dict[str, QAction] = {}
        self.view_menu.aboutToShow.connect(self._tick_view_menu)
        self._build_view_menu()
        # Deferred by a turn of the loop: adding or removing a pane is usually
        # this menu's own action doing it, and clearing a menu while it is
        # delivering a click is not somewhere to be.
        self.panes.changed.connect(lambda: QTimer.singleShot(0, self._build_view_menu))
        # A Memory pane opened, closed, let out or put back: the space for
        # them is shown or not to match.
        self.panes.changed.connect(lambda: QTimer.singleShot(0, self._update_memory_space))
        self.panes.pane_shown.connect(
            lambda _name, _shown: QTimer.singleShot(0, self._update_memory_space)
        )

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.setToolTipsVisible(True)
        self.packs_action = tools_menu.addAction("pyOCD device packs...", self._manage_packs)
        self.packs_action.setToolTip(
            "Find a device that is not in the list of targets, and install the\n"
            "CMSIS-Pack that describes it. Only pyOCD uses packs: J-Link Commander\n"
            "has SEGGER's own list of devices."
        )
        tools_menu.addSeparator()
        # What is set and left, apart from what is done. A submenu rather
        # than a menu of its own on the bar, because most settings live where
        # they are used, and a menu called Settings would look like the place
        # for all of them.
        self.settings_menu = QMenu("Settings", tools_menu)
        self.settings_menu.setToolTipsVisible(True)
        tools_menu.addMenu(self.settings_menu)
        self.theme_menu = theme.menu(self)
        self.settings_menu.addMenu(self.theme_menu)
        commander = self.settings_menu.addAction(
            "J-Link Commander location...", self._choose_commander
        )
        commander.setToolTip(
            "Where SEGGER's J-Link Commander is, for when pyflashgui does not find\n"
            "it by itself. It comes with SEGGER's J-Link software, and is only\n"
            "needed to use a J-Link through it."
        )
        # Below the line: not how pyflashgui behaves, but how this copy of it
        # is set up on this machine. For a source folder and for pip: the
        # installer makes its own entries.
        self.shortcut_action = self.desktop_action = None
        if shortcut.start() is not None:
            self.settings_menu.addSeparator()
            for place in shortcut.places():
                name = shortcut.place_name(place)
                action = self.settings_menu.addAction(
                    f"Add shortcut to {name}", lambda place=place: self._add_shortcut(place)
                )
                action.setToolTip(
                    f"Start pyflashgui from the {name}. From a source folder the entry\n"
                    "starts the launcher, so after a pull it still picks up new\n"
                    "libraries, as double-clicking the launcher does. Replaces one\n"
                    "made before."
                )
                if place == shortcut.ON_DESKTOP:
                    self.desktop_action = action
                else:
                    self.shortcut_action = action
        # Together, because "put something back the way it was" is one thing
        # to go looking for.
        self.reset_menu = tools_menu.addMenu("Reset")
        self.reset_menu.setToolTipsVisible(True)
        self.reset_menu.addAction(self.reset_layout_action)
        forget = self.reset_menu.addAction("Forget remembered folders", self._forget_folders)
        forget.setToolTip(
            "A file dialog opens where that sort of file was last used. This\n"
            "puts them all back to where they start."
        )
        ask_again = self.reset_menu.addAction("Re-enable all confirmations", self._ask_again)
        ask_again.setToolTip(
            "Bring back every confirmation you told pyflashgui not to ask again:\n"
            "erasing and programming a target."
        )

        self.help_menu = HelpMenu(self)

        self._say_how_to_add_a_shortcut()
        self.panes.restore_instances()
        self._build_view_menu()
        self._restore_layout()
        self.panes.restore_state()
        timing.mark("layout restored")
        # The detached windows were put back before this one was shown, so
        # it came up in front of them: a pane left on a second screen, hidden
        # behind the main window, might as well have been closed.
        QTimer.singleShot(0, self.panes.raise_detached)
        # Once the window is on screen: listing the targets loads the
        # flashing library, which is the slowest thing there is to load.
        QTimer.singleShot(0, self.probe_bar.start)

    # --- panes ---------------------------------------------------------------
    def _register_panes(self) -> None:
        """What sorts of pane there are, and which of them there can be several of.

        The test for a second instance is what it would show: a second Event
        Log is the same log twice. The order here is the order of the View
        menu.
        """
        for kind in (
            PaneKind(
                "files",
                "Files",
                Qt.LeftDockWidgetArea,
                lambda _name: FilesView(self.flasher, self.ctx, self.confirm),
            ),
            PaneKind(
                "memory",
                "Memory",
                Qt.RightDockWidgetArea,
                lambda _name: MemoryView(self.flasher, self.ctx),
                # One for each entry of the Files list that is shown:
                # Memory, Memory 2, and so on. Which there are follows
                # from that list, so they are not kept with the workspace,
                # and closing one closes it: the entry is still on the
                # list, to be shown again.
                several=True,
                transient=True,
            ),
            PaneKind("log", "Event Log", Qt.BottomDockWidgetArea, lambda _name: self.log),
            PaneKind(
                "console",
                "Python Console",
                Qt.BottomDockWidgetArea,
                lambda _name: ConsoleView(namespace(self, self.flash), self.flash, self.ctx),
                floating_first=True,
                floating_size=CONSOLE_PANE_SIZE,
            ),
        ):
            self.panes.register(kind)

    def _view_order(self) -> list[str]:
        """The panes, in the order the View menu should list them.

        The order they were *registered* in, which is the deliberate one,
        rather than the order they happened to be opened in. A workspace
        restores its panes in whatever order they were saved, so listing by
        that would make the menu reshuffle itself from one machine to the
        next, and a menu you cannot learn the shape of is one you read every
        time.
        """
        order = []
        for kind in self.panes.kinds:
            order.extend(name for name in self.panes.instances(kind) if name in self.panes.docks)
        order.extend(name for name in self.panes.names() if name not in order)
        return order

    def _pane_action(self, name: str) -> QAction:
        """A pane's entry in the View menu: ticked while it is on screen, anywhere.

        Not the dock's own show-and-hide action, which knows about the dock
        and nothing else. A pane out in a window of its own has its dock
        hidden, so that action would show it unticked while it was open.
        """
        action = QAction(self.panes.docks[name].windowTitle(), self.view_menu)
        action.setCheckable(True)
        action.setChecked(self.panes.on_screen(name))
        action.triggered.connect(lambda _checked=False, n=name: self._view_picked(n))
        self._view_actions[name] = action
        return action

    def _view_picked(self, name: str) -> None:
        """Show a pane, bring its window to the front, or put a docked one away.

        A pane in a window of its own is brought forward and stays open: it
        has a close button of its own, and somebody reaching for the menu
        with the window buried is looking for it, not trying to be rid of it.
        """
        dock = self.panes.docks.get(name)
        if dock is None:
            return
        if name in self.panes.detached or not self.panes.on_screen(name):
            self.panes.show(name)
        else:
            dock.hide()
        self._tick_view_menu()

    def _tick_view_menu(self) -> None:
        """Tick the panes that are on screen, as the menu is opened."""
        for name, action in self._view_actions.items():
            if (dock := self.panes.docks.get(name)) is not None:
                action.setText(dock.windowTitle())
                action.setChecked(self.panes.on_screen(name))

    def _build_view_menu(self) -> None:
        """Every pane, and the things you can do to the set of them."""
        self.view_menu.clear()
        self._view_actions = {}
        for name in self._view_order():
            self.view_menu.addAction(self._pane_action(name))
        self.view_menu.addSeparator()
        self.view_menu.addAction("Dock all panes", self.panes.dock_all)
        self.view_menu.addAction(self.reset_layout_action)

    def _arrange_default(self) -> None:
        """The layout a first run opens with, and what Reset layout goes back to.

            +-----------+--------------+
            |  Files    |  Memory      |
            +-----------+--------------+
            |        Event Log         |
            +--------------------------+

        What is open beside the bytes of it, a tab for each; and the log
        under both, because its lines are long.
        """
        files, log = (self.panes.docks[n] for n in DEFAULT_VISIBLE)
        self.addDockWidget(Qt.LeftDockWidgetArea, files)
        self.splitDockWidget(files, log, Qt.Vertical)
        self.resizeDocks([files, log], [7, 3], Qt.Vertical)
        for name in DEFAULT_VISIBLE:
            self.panes.docks[name].setVisible(True)
        # The place for the Memory panes, beside the Files pane and above
        # the log, which runs under both.
        space = self.memory_space
        space.show()
        self.splitDockWidget(files, space, Qt.Horizontal)
        self.resizeDocks([files, space], [1, 1], Qt.Horizontal)
        # The console starts hidden, and opens in front of the window when
        # it is asked for. Reset layout puts it back to that.
        for name in self.panes.instances("console"):
            self.panes.put_away(name)
        placed = None
        for name in self._memory_panes():
            if name in self.panes.detached:
                continue
            dock = self.panes.docks[name]
            dock.setFloating(False)
            self._dock_memory(dock, placed)
            dock.show()
            placed = placed or dock
        if placed is not None:
            placed.raise_()
        self._update_memory_space()

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.ContextMenu
            and isinstance(watched, QTabBar)
            and self._tab_menu(watched, event)
        ):
            return True
        # How wide the Files pane is while a Memory pane is beside it, kept
        # as it changes: by the time the last one has closed, Qt has already
        # given the Files pane its room.
        if (
            event.type() == QEvent.Resize
            and watched is self.panes.docks.get("files")
            and not self._closing
            and self._memory_docked()
        ):
            self._files_width = watched.width()
        return super().eventFilter(watched, event)

    def _make_memory_space(self) -> QDockWidget:
        label = QLabel(MEMORY_SPACE_TEXT)
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setEnabled(False)  # drawn in the quieter colour: it is a hint, not content
        label.setMargin(24)
        space = QDockWidget("Memory", self)
        space.setObjectName("memory_space")  # for saveState and restoreState
        space.setFeatures(QDockWidget.NoDockWidgetFeatures)
        space.setTitleBarWidget(QWidget())  # no title bar: there is nothing to do to it
        space.setWidget(label)
        self.addDockWidget(Qt.LeftDockWidgetArea, space)
        return space

    def _memory_docked(self) -> bool:
        """Whether a Memory pane is in the window, rather than in front of it or out."""
        return any(
            name not in self.panes.detached and not self.panes.docks[name].isFloating()
            for name in self._memory_panes()
        )

    def _update_memory_space(self) -> None:
        """Keep the place for the Memory panes while none is in it."""
        if self._closing:
            return
        space, files = self.memory_space, self.panes.docks["files"]
        wanted = not self._memory_docked()
        if wanted == space.isVisible():
            return
        if not wanted:
            space.hide()
            return
        space.show()
        # Back to how wide the Files pane was beside the Memory panes: Qt
        # hands the whole of what they leave to the pane next to them.
        if (width := self._files_width) and files.isVisible():
            # Once the space is laid out: sized before, it is sized twice.
            def restore() -> None:
                both = files.width() + space.width()
                self.resizeDocks([files, space], [width, max(both - width, 1)], Qt.Horizontal)

            QTimer.singleShot(0, restore)

    def _dock_memory(self, dock, beside) -> None:
        """Put a Memory pane in the window: a tab with another, or in the place kept for it."""
        if beside is not None:
            self.tabifyDockWidget(beside, dock)
            return
        space = self.memory_space
        if not space.isFloating() and space.isVisible():
            # Into the place kept for it, which then gives the place up.
            self.tabifyDockWidget(space, dock)
            self._update_memory_space()
            return
        files = self.panes.docks["files"]
        self.splitDockWidget(files, dock, Qt.Horizontal)
        self.resizeDocks([files, dock], [1, 1], Qt.Horizontal)

    def _restore_layout(self) -> None:
        # Where the window sits stays in QSettings: that belongs to this desk
        # and these monitors, and switching product should rearrange the panes
        # rather than move the window.
        if (geo := QSettings().value("geometry")) is not None:
            self.restoreGeometry(geo)
        state = self.ctx.layout.get("window")
        # restoreState declines a layout saved under an older LAYOUT_VERSION,
        # which leaves the default in place -- the same as never having run.
        restored = state is not None and self.restoreState(state, LAYOUT_VERSION)
        if restored:
            # A pane the saved layout puts on screen has a place already, and
            # must not be moved into a window of its own as a first time.
            self.panes.note_placed()
        if state is not None and not restored:
            # Said rather than silently starting from the default: somebody
            # who had arranged the panes deserves to know why they moved,
            # and "it forgot my layout after an update" is otherwise a
            # mystery reported as a bug.
            self.events.information(
                "The saved pane arrangement is from a version with a different set "
                "of panes, so this window opens with the default one."
            )
            # Every pane is unplaced again, so each opens in front of the
            # window the first time rather than as a sliver at the edge.
            self.panes.forget_arrangement()
        self.panes.restore_view_states()
        # Memory panes are not kept with a layout, so none is in the place
        # the saved layout kept for them.
        self._update_memory_space()

    def _reset_layout(self) -> None:
        """Put the panes back where they start, in a window the size it opens at.

        Arranged again rather than restored from a saved blob: splitter sizes
        captured before the window had ever been shown are the ones Qt had
        not worked out yet. Arranging a window that is on screen is the only
        way a pane's share of it means anything.

        The window itself is part of the arrangement: a layout put back
        inside a window somebody had dragged to a third of the screen is not
        the layout they were promised.
        """
        self._reset_geometry()
        self._arrange_default()

    def _reset_geometry(self) -> None:
        """The size it opens at, in the middle of the screen it is on."""
        self.showNormal()  # maximised or full screen, resizing does nothing
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(DEFAULT_WIDTH, available.width()), min(DEFAULT_HEIGHT, available.height()))
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def save_arrangement(self) -> None:
        """Write the pane arrangement into the workspace now.

        Not where the window sits on the screen, which stays in QSettings
        with this machine.
        """
        self.ctx.layout.set("window", bytes(self.saveState(LAYOUT_VERSION)))
        self.panes.save_view_states()
        self.panes.save()

    def run_script_in_console(self, path: str) -> None:
        """File > Run script... and Recent scripts: in the console, shown, so
        that what the script prints is there to be read."""
        if self.console.running:
            self.events.warning(
                f"{Path(path).name} was not run: the Python Console is still running something."
            )
            return
        self.panes.show("console")
        self.console.run_file(path)

    def script_running(self) -> bool:
        """Whether the Python Console is running something."""
        return any(
            getattr(self.panes.view(name), "running", False)
            for name in self.panes.instances("console")
        )

    def closeEvent(self, event) -> None:
        # Not while a target is being written to: closing would abandon it
        # half programmed, with nothing left on screen to say so.
        if self.flasher.busy and not self._closing:
            self._refuse_close(
                "pyflashgui is still working on the target. Close it when that has finished.",
                "A read or a verify can be stopped with Cancel, beside the progress bar. "
                "Erasing and programming cannot be stopped part way: that would leave the "
                "target holding neither the old firmware nor the new.",
            )
            event.ignore()
            return
        # Nor while a script is: it is part way through something, on this
        # window's own thread, and would be left wherever it had got to.
        if self.script_running() and not self._closing:
            self._refuse_close(
                "A script is running in the Python Console. Stop it, then close pyflashgui.",
                "Stop, in the Python Console, stops it at the next thing it asks of the probe.",
            )
            event.ignore()
            return
        # Each read that has not been saved is asked about, and one that
        # is to be kept keeps the whole of pyflashgui open.
        if not self._closing and not (self.files_view.may_close() and self.panes.may_close_all()):
            event.ignore()
            return
        # Everything is about to be hidden, and reporting each pane going away
        # on the way out would be a paragraph nobody asked for.
        self._closing = True
        self.closing.emit()
        QSettings().setValue("geometry", self.saveGeometry())
        # Saved before they are closed: closing one puts its pane away, and
        # what is saved should be how things were left, not how they were
        # tidied up.
        self.save_arrangement()
        # Parentless windows of their own, so they would keep the application
        # running after the main window had gone.
        self.panes.close_detached()
        self.help_menu.shutdown()
        self.packs.shutdown()
        self.flasher.shutdown()
        self.exceptions.remove()
        super().closeEvent(event)

    def _refuse_close(self, said: str, more: str) -> None:
        """Say why the window is staying open: in the Event Log, and in a box.

        The box because closing is asked for by somebody who has stopped looking
        at the Event Log: a line there alone looked like nothing happening.
        """
        self.events.warning(said)
        messages.warning(self, "pyflashgui is busy", f"{said}\n\n{more}")

    # --- tools ---------------------------------------------------------------
    def _switch_workspace(self, name: str) -> None:
        """Open another workspace, once whoever is connected has agreed to it.

        A workspace holds which probe and which target, so opening one
        means letting go of the target this one is connected to. Worth a
        question, and only when there is something to lose. Not at all
        while a target is being written to: that is left to finish.
        """
        if name == self.ctx.workspace or not workspaces.exists(name):
            return
        if self.flasher.busy:
            self.events.warning(
                "pyflashgui is still working on the target. Open another workspace "
                "when that has finished."
            )
            return
        if self.flasher.connected and not self.confirm.ask(
            self,
            "workspace-switch",  # agreed once a session: it is the same loss each time
            "Disconnect and open another workspace?",
            SWITCH_WHILE_CONNECTED.format(target=self.flasher.target, name=name),
        ):
            return
        self.reopen_requested.emit(name)

    def _refresh_map(self) -> None:
        """Lay what is ticked over the target's memory again."""
        target = self.flasher.target if self.flasher.connected else (self.probe_bar.chosen_target())
        self.map_view.show_layout(
            self.files_view.loaded(),
            self.flasher.regions,
            target,
            self.flasher.backend.map_is_complete,
        )
        self._show_device(target)

    def _show_device(self, target: str) -> None:
        """Say in the status bar what is known of the target that is chosen."""
        info = self._targets.get(target.upper())
        self.device_label.setText(describe_device(target, info, self.flasher.regions))

    def _on_targets(self, targets: list) -> None:
        self._targets = {target.name.upper(): target for target in targets}
        self._refresh_map()

    def _choose_commander(self) -> None:
        """Tools > Settings > J-Link Commander location."""
        found = jlink_backend.find_commander()
        start = found[0] if found else str(Path.home())
        path, _type = QFileDialog.getOpenFileName(
            self,
            "Where J-Link Commander is",
            start,
            f"J-Link Commander ({jlink_backend.PROGRAM});;All files (*)",
        )
        if not path:
            return
        QSettings().setValue(COMMANDER_SETTING, path)
        jlink_backend.set_commander(path)
        self.events.information(f"J-Link Commander is {path}.")
        self.flasher.refresh_targets()
        self.flasher.refresh_probes()

    def _manage_packs(self) -> None:
        """Tools > pyOCD device packs."""
        dialog = PacksDialog(self.packs, self, self.ctx)
        dialog.chosen.connect(self._use_target)
        dialog.exec()
        dialog.deleteLater()

    def _use_target(self, name: str) -> None:
        """A device was picked in the packs dialog to be the target."""
        if self.flasher.connected or self.flasher.busy:
            self.events.warning(
                f"{name} was not made the target: disconnect first, and choose it in the bar."
            )
            return
        self.probe_bar.choose_target(name)
        self.events.information(f"The target is {name}.")

    def _read_memory(self) -> None:
        """Ask what to read from the target, and read it."""
        dialog = ReadDialog(self.flasher.regions, self, self.flasher.backend.can_skip_setup)
        if dialog.exec() != ReadDialog.Accepted or (asked := dialog.values()) is None:
            return
        self.flasher.read_memory(*asked, skip_setup=dialog.skips_setup())

    def _show_memory(self, address: int, data: bytes, target: str) -> None:
        """Take these bytes as read from a target: on the list, and in a pane."""
        self.files_view.add_read(address, data, target)

    def _pane_of(self, entry: Entry) -> str:
        """The Memory pane that shows this entry, by name. Empty when none does."""
        for name in self._memory_panes():
            if self.panes.view(name).entry is entry:
                return name
        return ""

    def _open_memory(self, entry: Entry, in_window_only: bool = False) -> None:
        """Show an entry of the Files list in a Memory pane of its own.

        The one it has, if it has one. Otherwise a new one: a tab with the
        last that is docked in the window, since once one has been put
        somewhere that is where the rest are wanted; beside the Files pane
        when there is none; and in front of the window when the Files pane
        is not in it either.
        """
        if name := self._pane_of(entry):
            self.panes.show(name)
            return
        docked = [
            self.panes.docks[n]
            for n in self._memory_panes()
            if n not in self.panes.detached
            and not self.panes.docks[n].isFloating()
            and not self.panes.docks[n].isHidden()
        ]
        files = self.panes.docks["files"]
        beside_files = (
            "files" not in self.panes.detached and not files.isFloating() and not files.isHidden()
        )
        in_window = bool(docked) or beside_files
        if in_window_only and not in_window:
            return
        name = self.panes.add("memory", floating=not in_window)
        if not name:
            return
        view = self.panes.view(name)
        view.read_requested.connect(self._read_memory)
        view.saved.connect(self.files_view.refill)
        view.cropped.connect(self.files_view.add_crop)
        view.show_entry(entry)
        # Called what the list calls it, which is how the two are told to be one.
        self.panes.set_default_title(name, view.title())
        dock = self.panes.docks[name]
        if in_window:
            self._dock_memory(dock, docked[-1] if docked else None)
        else:
            dock.resize(
                max(dock.width(), MEMORY_PANE_SIZE[0]), max(dock.height(), MEMORY_PANE_SIZE[1])
            )
        dock.show()
        dock.raise_()
        # Dragged out of the window or back into it: the space follows.
        dock.topLevelChanged.connect(lambda _floating: self._update_memory_space())
        # Its tab, when it is one, is made by Qt as the panes are laid out:
        # looked for once that has happened, and again whenever it is moved.
        QTimer.singleShot(0, self._watch_tab_bars)
        dock.dockLocationChanged.connect(lambda _area: QTimer.singleShot(0, self._watch_tab_bars))

    def _compare(self, shown: Entry, other: Entry) -> None:
        """Show one entry, marked where another differs from it.

        The other is marked too, against the first, when it is open in a pane
        of its own: either one can be looked at to see the differences.
        """
        self._open_memory(shown)
        if name := self._pane_of(shown):
            self.panes.view(name).compare_with(other.image)
        if (name := self._pane_of(other)) and shown.image is not None:
            self.panes.view(name).compare_with(shown.image, quiet=True)

    def _close_memory(self, entry: Entry) -> None:
        """An entry has gone from the list, and the pane that showed it goes too."""
        if name := self._pane_of(entry):
            self.panes.remove(name)

    def _on_files_changed(self) -> None:
        self._refresh_map()
        # A build wrote a file again, or a raw binary was given its address.
        for view in self.memory_views:
            view.refresh()

    @property
    def map_view(self) -> MapView:
        """Where the ticked entries land: part of the Files pane."""
        return self.files_view.map_view

    # --- a Memory pane's tab, right-clicked ---------------------------------------
    def _watch_tab_bars(self) -> None:
        """Listen to the tab bars Qt makes for panes in tabs, for a right click.

        Qt makes them as panes are put together, and answers a right click on
        one with its own menu of panes, so each is watched as it appears.
        """
        for bar in self.findChildren(QTabBar):
            if not bar.property("pyflashgui_watched"):
                bar.setProperty("pyflashgui_watched", True)
                bar.installEventFilter(self)

    def _tab_menu(self, bar: QTabBar, event) -> bool:
        """Close, for a Memory pane's tab: with several open, the tabs are where
        they are told apart. Whether the right click was one of those."""
        if not (name := self._memory_tab(bar, bar.tabAt(event.pos()))):
            return False
        self.memory_tab_menu(name).exec(event.globalPos())
        return True

    def _memory_tab(self, bar: QTabBar, index: int) -> str:
        """The Memory pane a tab is for, by name: empty for another pane's."""
        if index < 0:
            return ""
        title = bar.tabText(index)
        return next(
            (n for n in self._memory_panes() if self.panes.docks[n].windowTitle() == title), ""
        )

    def memory_tab_menu(self, name: str) -> QMenu:
        """What a right click on a Memory pane's tab offers. Each is closed as its
        own close button closes it: put away, and shown again with its entry."""
        menu = QMenu(self)
        others = [n for n in self._memory_panes() if n != name and self.panes.on_screen(n)]
        menu.addAction("Close", lambda: self.panes.docks[name].close())
        close_others = menu.addAction(
            "Close the other Memory panes", lambda: [self.panes.docks[n].close() for n in others]
        )
        close_others.setEnabled(bool(others))
        menu.addAction(
            "Close all Memory panes",
            lambda: [self.panes.docks[n].close() for n in [name, *others]],
        )
        return menu

    def _memory_panes(self) -> list[str]:
        """The Memory panes that are open, by name, oldest first."""
        return [name for name in self.panes.instances("memory") if name in self.panes.docks]

    @property
    def memory_views(self) -> list[MemoryView]:
        return [self.panes.view(name) for name in self._memory_panes()]

    @property
    def memory_view(self) -> MemoryView | None:
        """What the newest Memory pane shows, or None when there are none."""
        views = self.memory_views
        return views[-1] if views else None

    def _forget_folders(self) -> None:
        count = folders.forget_all(self.ctx)
        self.events.information(
            "Every file dialog opens where it starts again."
            if count
            else "No folders were being remembered."
        )

    def _ask_again(self) -> None:
        self.confirm.forget_everything()
        self.events.information("Every confirmation will be asked again.")

    def _add_shortcut(self, place: str = shortcut.IN_MENU) -> None:
        """Tools > Settings > Add shortcut to Start menu, or to desktop."""
        name = shortcut.place_name(place)
        try:
            path = shortcut.create(place=place)
        except OSError as exc:
            self.events.error(f"Could not add pyflashgui to the {name}: {exc}")
            return
        self.events.good(f"Added pyflashgui to the {name}: {path}")

    def _say_how_to_add_a_shortcut(self) -> None:
        """Once for each person on a machine, for a source folder or pip: the
        launcher no longer asks, and pip never did, so say where it is done.
        Not where there is one already, nor for the installer, which made its own."""
        if shortcut.start() is None or QSettings().value(SHORTCUT_TOLD_KEY) is not None:
            return
        QSettings().setValue(SHORTCUT_TOLD_KEY, True)
        if shortcut.made():
            return
        names = " or the ".join(shortcut.place_name(place) for place in shortcut.places())
        self.events.information(
            f"To start pyflashgui from the {names}: Tools > Settings > Add shortcut. "
            "This is said once."
        )

    # --- the Event Log -------------------------------------------------------
    @Slot(str, str)
    def _on_event(self, message: str, level: str) -> None:
        """The only thing that writes to the Event Log pane.

        Which is what makes giving each level a colour a change here and
        nowhere else. Written through a cursor rather than appendPlainText
        so the line can carry a format, and as text rather than as HTML so
        that a traceback keeps its indentation and nothing in a probe's own
        message can be read as markup.

        The view is only dragged to the bottom if it was already there:
        somebody scrolled up reading the fault that just went past should
        not be pulled away from it by the next line.
        """
        bar = self.log.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - AT_END
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        shape = QTextCharFormat()
        if (colour := event_colours.colour_for(level, self._dark_log())) is not None:
            shape.setForeground(colour)
        if event_colours.bold_for(level):
            shape.setFontWeight(QFont.Bold)
        cursor.insertText(message, shape)
        # Painted again as a whole. Written through a cursor, a line could be
        # drawn before its colour was laid out, and stayed in the plain text
        # colour until scrolling redrew it -- an error that did not look like one.
        self.log.viewport().update()
        if at_end:
            bar.setValue(bar.maximum())
        if level in PROBLEMS:
            self._surface_log()

    def log_menu(self):
        """Copy and Select All as usual, and Clear. Built apart from being shown."""
        menu = self.log.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear", self.log.clear)
        return menu

    def _log_menu(self, at) -> None:
        menu = self.log_menu()
        menu.exec(self.log.viewport().mapToGlobal(at))
        menu.deleteLater()

    def _dark_log(self) -> bool:
        """Which set of colours reads on the Event Log's own background."""
        return event_colours.dark_behind(self.log.palette())

    def _surface_log(self) -> None:
        """Open the Event Log, because something in it needs reading.

        Deferred by a turn of the event loop for two reasons: a problem raised
        while the window is still being built would otherwise be undone by the
        saved layout, which is restored afterwards; and a burst of them should
        cost one show rather than twenty.
        """
        if self._surfacing:
            return
        self._surfacing = True
        QTimer.singleShot(0, self._show_log)

    def _show_log(self) -> None:
        self._surfacing = False
        panes = getattr(self, "panes", None)
        dock = None if panes is None else panes.docks.get("log")
        if dock is None or "log" in panes.detached:
            return  # too early to have a pane, or it has a window of its own
        if not dock.isVisible():
            dock.show()
        dock.raise_()  # it may be docked but tabbed behind another pane
