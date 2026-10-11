# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Files pane: the memories that are open, and the buttons that use them.

A list of what is open -- firmware files, and what has been read from a
target -- each ticked or not, with where the ticked ones land underneath, and
Erase, Program, Verify, Reset and Read beside it. A file and a read are the
same thing here: bytes at addresses, to look at, to compare and to write.
The files are kept in the workspace, so that programming a product is
choosing its workspace and pressing Program. What was read is not: it is
in memory until it is saved, and then it is a file like any other.

**A file is read again every time it is used.** It is what a build has just
written, and a list that programmed what the file held when it was added
would program yesterday's firmware without a word. The file is watched as
well, so the sizes and the memory map on screen follow each build.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.backends.base import ERASE_CHIP, ERASE_SECTORS
from pyflashgui.core import images
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher, size_text
from pyflashgui.core.images import Image, ImageError, Segment
from pyflashgui.core.memory_map import lay_out
from pyflashgui.ui import folders, fonts, messages
from pyflashgui.ui.confirm import Confirmations
from pyflashgui.ui.erase_dialog import EraseDialog
from pyflashgui.ui.map_view import MapView
from pyflashgui.ui.persist import remember

FILES_KEY = "files.list"

FILE, FORMAT, ADDRESS, END, SIZE = range(5)
HEADINGS = ("Name", "Source", "From", "To", "Size")

ADDRESS_TIP = (
    "Where a raw binary starts. It carries no addresses of its own, so it\n"
    "cannot be programmed until it is given one, in hexadecimal. A file that\n"
    "has its own addresses shows where its first byte goes."
)
#: How long after a file changes it is read again. A linker writes a file in
#: pieces, and reading it between two of them reads half a file.
SETTLE_MS = 300


@dataclass(eq=False)
class Entry:
    """One memory in the list: a file and what reading it last found, or a read.

    Each is itself and no other, however alike two are: two reads of the
    same range are two entries, and a pane shows one of them.
    """

    #: Where the file is. For what was read from a target, its name.
    path: str
    #: Where a raw binary starts, typed in. None until it has been.
    address: int | None = None
    enabled: bool = True
    image: Image | None = None
    #: Why it could not be read, when it could not.
    problem: str = ""
    #: The target it was read from, for one that was. Empty for a file.
    target: str = ""
    #: When it was read from the target, as it is shown.
    when: str = ""
    #: Whether what was read is anywhere but here. True from the moment
    #: it is read until it has been saved.
    unsaved: bool = False

    @property
    def is_read(self) -> bool:
        """Whether this was read from a target, and so is held and not on disc."""
        return bool(self.target)

    @property
    def name(self) -> str:
        return self.path if self.is_read else Path(self.path).name

    def read(self) -> None:
        if self.is_read:
            return  # there is no file to read it from again
        try:
            self.image, self.problem = images.read(self.path, self.address), ""
        except ImageError as exc:
            self.image, self.problem = None, str(exc)


def parse_address(text: str) -> int | None:
    """A hexadecimal address as somebody would type it, or None if it is not one."""
    text = text.strip().replace("_", "").replace(" ", "")
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        value = int(text, 16)
    except ValueError:
        return None
    return value if 0 <= value <= 0xFFFF_FFFF else None


def save_entry(parent: QWidget, ctx: Context, entry: Entry, data: bytes | None = None) -> bool:
    """Ask where, and save what an entry holds there. Whether it was saved.

    For one that is a single run of bytes, which what is read always is.
    ``data`` is for saving less than all of it: the same bytes with the
    erased ones left off the end.
    """
    segment = entry.image.segments[0]
    address = segment.address
    data = segment.data if data is None else data
    source = entry.target if entry.is_read else Path(entry.path).stem
    path = folders.save_file(
        parent,
        ctx,
        folders.EXPORT,
        "Save what was read" if entry.is_read else "Save a copy",
        images.WRITE_FILTER,
        Path.home(),
        # The time in the name: a read is saved to be kept, and the
        # next one must not offer to overwrite it.
        suggested=folders.stamped(f"{source}_{address:08X}", ".bin"),
    )
    if not path:
        return False
    try:
        fmt = images.write(path, address, data)
    except ImageError as exc:
        ctx.events.error(f"Saving to {path} failed: {exc}")
        return False
    entry.unsaved = False
    ctx.events.good(
        f"Saved {size_text(len(data))} from {address:08X} of {entry.target or entry.name} "
        f"as {fmt} in {path}."
    )
    return True


def may_discard(parent: QWidget, ctx: Context, entry: Entry, title: str) -> bool:
    """Whether a read may be let go of: asked, if it has not been saved.

    What was read is only in memory until it is saved, so letting go of
    one that has not been says so first. It can then be saved, thrown
    away, or kept; and a Save that was cancelled, or failed, has saved
    nothing, and keeps it too.
    """
    if not entry.unsaved:
        return True
    answer = messages.warning(
        parent,
        title,
        f"{entry.name} is what was read from {entry.target}, and has not been saved. "
        "Without saving, it is thrown away.",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        QMessageBox.Cancel,
    )
    if answer == QMessageBox.Save:
        return save_entry(parent, ctx, entry)
    return answer == QMessageBox.Discard


class FilesView(QWidget):
    #: The list, or what is in one of its files, changed: the memory map
    #: and whatever shows an entry are out of date.
    changed = Signal()
    #: An entry is to be shown: it has just been added, or was asked for.
    opened = Signal(object)
    #: An entry has been taken off the list.
    removed = Signal(object)
    #: Two entries are to be compared: the one to show, and the one to mark
    #: it against.
    compare_requested = Signal(object, object)
    #: Read... was pressed: the window asks what to read and reads it.
    read_requested = Signal()

    def __init__(self, flasher: Flasher, ctx: Context, confirm: Confirmations) -> None:
        super().__init__()
        self.flasher = flasher
        self.ctx = ctx
        self.confirm = confirm
        self.entries: list[Entry] = []
        self._filling = False
        #: How many reads there have been, for naming the next.
        self._reads = 0
        #: Where the ticked entries land, under the list they are ticked in.
        self.map_view = MapView()

        self.table = QTableWidget(0, len(HEADINGS))
        self.table.setHorizontalHeaderLabels(HEADINGS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAccessibleName("Open files and reads")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(FILE, QHeaderView.Stretch)
        for column in (FORMAT, ADDRESS, END, SIZE):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._enable)
        self.table.itemDoubleClicked.connect(self._on_double_click)

        self.add_button = QPushButton("Add...")
        self.add_button.setToolTip("Add firmware files: ELF, Intel HEX, S-record or raw binary.")
        self.add_button.clicked.connect(self._add_dialog)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip(
            "Take the selected off the list. A file is kept; a read that has not\n"
            "been saved is asked about first."
        )
        self.remove_button.clicked.connect(self.remove_selected)
        self.show_button = QPushButton("Show")
        self.show_button.setToolTip(
            "Show the bytes of the selected in a Memory pane. Double-clicking one\ndoes the same."
        )
        self.show_button.clicked.connect(self.show_selected)
        self.compare_button = QPushButton("Compare")
        self.compare_button.setToolTip(
            "Compare the two that are selected -- two reads, two files, or one of\n"
            "each -- and mark where they differ in a Memory pane. Nothing is read\n"
            "from the target. Ctrl+click selects a second."
        )
        self.compare_button.clicked.connect(self.compare_selected)

        self.chip_erase = QCheckBox("Erase everything first")
        self.chip_erase.setToolTip(
            "Erase all of the flash before programming, so that nothing of what\n"
            "was there is left. Without it, only the sectors the ticked write to\n"
            "are erased, and the rest of the flash is kept."
        )
        self.verify_after = QCheckBox("Verify")
        self.verify_after.setChecked(True)
        self.verify_after.setToolTip(
            "Read the flash back after programming and compare it with what was written."
        )
        self.reset_after = QCheckBox("Reset")
        self.reset_after.setChecked(True)
        self.reset_after.setToolTip(
            "Restart the target after programming, so the new firmware runs."
        )
        remember(ctx, "files.chip_erase", self.chip_erase)
        remember(ctx, "files.verify", self.verify_after)
        remember(ctx, "files.reset", self.reset_after)

        self.program_button = QPushButton("Program")
        self.program_button.setToolTip("Write the ticked files and reads to the target.")
        self.program_button.clicked.connect(self.program)
        self.verify_button = QPushButton("Verify")
        self.verify_button.setToolTip(
            "Compare what is in the target with what is ticked, changing nothing."
        )
        self.verify_button.clicked.connect(self.verify)
        self.erase_button = QPushButton("Erase...")
        self.erase_button.setToolTip(
            "Erase the target's flash: all of it, some of its regions, or a range."
        )
        self.erase_button.clicked.connect(self.erase)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Restart the target.")
        self.reset_button.clicked.connect(self.flasher.reset)
        self.read_button = QPushButton("Read...")
        self.read_button.setToolTip(
            "Read part of the target's memory back, changing nothing in the target.\n"
            "What is read joins the list, and is shown in a Memory pane of its own."
        )
        self.read_button.clicked.connect(self.read_requested.emit)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(True)
        self.progress.setFormat("")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip(
            "Stop verifying or reading. Programming is not stopped part way: that would\n"
            "leave the target holding neither the old firmware nor the new."
        )
        self.cancel_button.clicked.connect(self.flasher.cancel)

        files_row = QHBoxLayout()
        for widget in (
            self.add_button,
            self.remove_button,
            self.show_button,
            self.compare_button,
        ):
            files_row.addWidget(widget)
        files_row.addStretch(1)
        for widget in (self.chip_erase, self.verify_after, self.reset_after):
            files_row.addWidget(widget)
        actions_row = QHBoxLayout()
        for widget in (
            self.program_button,
            self.verify_button,
            self.erase_button,
            self.reset_button,
            self.read_button,
        ):
            actions_row.addWidget(widget)
        actions_row.addWidget(self.progress, 1)
        actions_row.addWidget(self.cancel_button)
        listed = QWidget()
        list_layout = QVBoxLayout(listed)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self.table, 1)
        list_layout.addLayout(files_row)
        #: The list over the map of it, with the room shared as wanted.
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(listed)
        self.splitter.addWidget(self.map_view)
        self.splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter, 1)
        layout.addLayout(actions_row)

        #: Reads a file again when a build writes it. Once it has settled:
        #: see SETTLE_MS.
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._changed_files: set[str] = set()
        self._settle = QTimer(self, singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(self._reread_changed)

        flasher.connection_changed.connect(lambda _on: self._enable())
        flasher.busy_changed.connect(self._on_busy)
        flasher.progress.connect(self._on_progress)
        flasher.finished.connect(self._on_finished)
        flasher.memory_read.connect(self.add_read)
        self._load()
        self._enable()

    # --- the list --------------------------------------------------------------------
    def _load(self) -> None:
        for saved in self.ctx.settings.get(FILES_KEY, []) or []:
            if not isinstance(saved, dict) or not saved.get("path"):
                continue
            address = saved.get("address")
            self.entries.append(
                Entry(
                    path=str(saved["path"]),
                    address=address if isinstance(address, int) else None,
                    enabled=bool(saved.get("enabled", True)),
                )
            )
        for entry in self.entries:
            entry.read()
            self._watch(entry.path)
        self._fill()

    def _save(self) -> None:
        self.ctx.settings.set(
            FILES_KEY,
            [
                {"path": e.path, "address": e.address, "enabled": e.enabled}
                for e in self.entries
                # Not what was read: there would be nothing to open next time.
                if not e.is_read
            ],
        )

    def _watch(self, path: str) -> None:
        if Path(path).exists() and path not in self._watcher.files():
            self._watcher.addPath(path)

    def add_files(self, paths: list[str]) -> None:
        """Put these files on the list, each once."""
        have = {Path(e.path) for e in self.entries if not e.is_read}
        added = []
        for path in paths:
            if Path(path) in have:
                continue
            have.add(Path(path))
            entry = Entry(path=str(path))
            entry.read()
            self.entries.append(entry)
            added.append(entry)
            self._watch(entry.path)
            if entry.image is not None:
                self.ctx.events.information(f"Added {entry.image.summary()}")
        self._changed()
        for entry in added:
            if entry.image is not None:
                self.opened.emit(entry)

    def add_read(self, address: int, data: bytes, target: str) -> Entry:
        """Put what has just been read from a target on the list, and show it.

        Not ticked: a read is made to be looked at, and one that was
        ticked would be written back by the next Program, over whatever
        the files have for the same addresses.
        """
        self._reads += 1
        name = f"Read {self._reads}"
        entry = Entry(
            path=name,
            enabled=False,
            image=Image(name, images.BINARY, (Segment(address, data),)),
            target=target,
            when=f"{datetime.now():%H:%M:%S}",
            unsaved=True,
        )
        self.entries.append(entry)
        self._changed()
        self.opened.emit(entry)
        return entry

    def _selected(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def remove_selected(self) -> None:
        gone = []
        for row in reversed(self._selected()):
            entry = self.entries[row]
            if not may_discard(self, self.ctx, entry, "Remove without saving?"):
                continue
            gone.append(self.entries.pop(row))
            if entry.path in self._watcher.files():
                self._watcher.removePath(entry.path)
        if gone:
            self._changed()
        for entry in gone:
            self.removed.emit(entry)

    def show_selected(self) -> None:
        for row in self._selected():
            self.opened.emit(self.entries[row])

    def compare_selected(self) -> None:
        """Compare the two selected: one is shown, marked where the other differs.

        The one shown is the read, of a read and a file: what is in the
        target is what is being looked into, and the file is what it is
        held against. Of two of a kind, it is the one higher in the list.
        """
        chosen = [self.entries[row] for row in self._selected()]
        if len(chosen) != 2:
            return
        for entry in chosen:
            if entry.image is None:
                self.ctx.events.error(
                    f"{entry.name} cannot be read, so there is nothing to compare: {entry.problem}"
                )
                return
        shown, other = chosen
        if other.is_read and not shown.is_read:
            shown, other = other, shown
        self.compare_requested.emit(shown, other)

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        # Not where a double click is how an address is typed.
        if not item.flags() & Qt.ItemIsEditable:
            self.opened.emit(self.entries[item.row()])

    def refill(self) -> None:
        """Show the list again, when something about an entry has changed."""
        self._fill()

    def may_close(self) -> bool:
        """Ask about each read that has not been saved. False at the first kept."""
        kept = not all(
            may_discard(self, self.ctx, entry, "Close without saving?")
            for entry in self.entries
            if entry.unsaved
        )
        self._fill()  # one that was saved on the way no longer says it is not
        return not kept

    def _add_dialog(self) -> None:
        path = folders.open_file(
            self,
            self.ctx,
            folders.IMAGE,
            "Add a firmware file",
            images.READ_FILTER,
            Path.home(),
        )
        if path:
            self.add_files([path])

    def _changed(self) -> None:
        self._save()
        self._fill()
        self.changed.emit()

    def _fill(self) -> None:
        self._filling = True
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            name = QTableWidgetItem(entry.name)
            name.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name.setCheckState(Qt.Checked if entry.enabled else Qt.Unchecked)
            image = entry.image
            if entry.is_read:
                source = f"{entry.target}, read {entry.when}"
                source += ", not saved" if entry.unsaved else ""
                name.setToolTip(
                    f"Read from {entry.target} at {entry.when}. Ticked, it is written "
                    "by Program like a file."
                )
            else:
                source = image.format if image else "Not read"
                name.setToolTip(entry.path)
            format_item = QTableWidgetItem(source)
            size = QTableWidgetItem(size_text(image.size) if image else "")
            end = QTableWidgetItem(
                f"{max(s.end for s in image.segments) - 1:08X}" if image and image.segments else ""
            )
            end.setFont(fonts.mono())
            needs_address = image is None and images.looks_binary(entry.path)
            is_binary = not entry.is_read and (
                (image is not None and image.format == images.BINARY) or needs_address
            )
            if image is not None:
                address = QTableWidgetItem(f"{image.address:08X}")
            else:
                address = QTableWidgetItem("" if entry.address is None else f"{entry.address:08X}")
            address.setFont(fonts.mono())
            address.setToolTip(ADDRESS_TIP)
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            address.setFlags(flags | Qt.ItemIsEditable if is_binary else flags)
            for item in (format_item, end, size):
                item.setFlags(flags)
            if entry.problem:
                # In words in the row, and whole in the tooltip: a row that
                # only turned a colour would not say what was wrong with it.
                format_item.setText("Cannot be read")
                for item in (name, format_item, address, end, size):
                    item.setToolTip(f"{entry.path}\n\n{entry.problem}")
            for column, item in enumerate((name, format_item, address, end, size)):
                self.table.setItem(row, column, item)
        self._filling = False
        self._enable()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        entry = self.entries[item.row()]
        if item.column() == FILE:
            enabled = item.checkState() == Qt.Checked
            if enabled != entry.enabled:
                entry.enabled = enabled
                self._save()
                self.changed.emit()
        elif item.column() == ADDRESS:
            address = parse_address(item.text())
            if address is None:
                self.ctx.events.warning(
                    f"{item.text()!r} is not an address: it wants hexadecimal, such as 08000000."
                )
            else:
                entry.address = address
                entry.read()
            # Filled again either way, so the cell shows what was taken and
            # not what was typed.
            self._changed()

    # --- following the files on disc -------------------------------------------------
    def _on_file_changed(self, path: str) -> None:
        self._changed_files.add(path)
        self._settle.start()

    def _reread_changed(self) -> None:
        paths, self._changed_files = self._changed_files, set()
        for entry in self.entries:
            if entry.path in paths:
                entry.read()
                # A build that replaces the file, rather than writing over
                # it, takes the watch away with the old one.
                self._watch(entry.path)
        self._fill()
        self.changed.emit()

    # --- what is to be programmed ----------------------------------------------------
    def loaded(self) -> list[Image]:
        """What is ticked, the files as they were last read, for the memory map."""
        return [e.image for e in self.entries if e.enabled and e.image is not None]

    def reread(self) -> list[Image] | None:
        """What is ticked, the files read now. None, having said why, if one cannot be."""
        ticked = [e for e in self.entries if e.enabled]
        for entry in ticked:
            entry.read()
        self._fill()
        self.changed.emit()
        failed = [e for e in ticked if e.image is None]
        for entry in failed:
            self.ctx.events.error(f"{entry.name} cannot be read: {entry.problem}")
        return None if failed else [e.image for e in ticked]

    # --- the buttons -----------------------------------------------------------------
    def _may(self, key: str, title: str, text: str) -> bool:
        """Ask before changing a target, once a session for each target."""
        if self.flasher.backend.name == "simulated":
            return True  # nothing real is on the end of it
        return self.confirm.ask(self, f"{key}:{self.flasher.target}", title, text)

    def program(self) -> None:
        if (files := self.reread()) is None:
            return
        if not files:
            self.ctx.events.warning("There is nothing to program: nothing is ticked.")
            return
        # Checked against the target that is actually connected, with the
        # bytes that were just read: the same check the Memory Map shows.
        layout = lay_out(files, self.flasher.regions, self.flasher.backend.map_is_complete)
        for problem in layout.problems:
            self.ctx.events.post(problem.message, problem.level)
        if not layout.programmable:
            self.ctx.events.error("Not programmed: the Memory Map says what is wrong.")
            return
        everything = self.chip_erase.isChecked()
        target = self.flasher.target
        if not self._may(
            "program",
            f"Program {target}?",
            f"This replaces what {target} holds"
            + (
                ": all of its flash is erased first."
                if everything
                else " in the sectors that what is ticked writes to."
            )
            + " It cannot be undone.",
        ):
            return
        self.flasher.program(
            files,
            erase=ERASE_CHIP if everything else ERASE_SECTORS,
            verify=self.verify_after.isChecked(),
            reset=self.reset_after.isChecked(),
        )

    def verify(self) -> None:
        if (files := self.reread()) is not None:
            self.flasher.verify(files)

    def erase(self) -> None:
        """Ask how much to erase, ask whether to, and erase it."""
        dialog = EraseDialog(self.flasher.regions, self)
        if dialog.exec() != EraseDialog.Accepted:
            return
        ok, ranges = dialog.chosen()
        if not ok:
            return
        target = self.flasher.target
        if ranges is None:
            title = f"Erase all of the flash of {target}?"
            text = (
                "Everything it holds is lost, and it will not run until it is "
                "programmed again. It cannot be undone."
            )
        else:
            title = f"Erase part of the flash of {target}?"
            spans = ", ".join(f"{a:08X} to {a + n - 1:08X}" for a, n in ranges)
            text = (
                f"What is in {spans} is lost, with the rest of every sector those "
                "addresses fall in. It cannot be undone."
            )
        if self._may("erase", title, text):
            self.flasher.erase(ranges)

    # --- following the flasher -------------------------------------------------------
    def _enable(self) -> None:
        connected, busy = self.flasher.connected, self.flasher.busy
        ready = connected and not busy
        ticked = any(e.enabled for e in self.entries)
        self.program_button.setEnabled(ready and ticked)
        self.verify_button.setEnabled(ready and ticked)
        self.erase_button.setEnabled(ready)
        self.reset_button.setEnabled(ready)
        self.read_button.setEnabled(ready)
        self.cancel_button.setEnabled(busy)
        self.add_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy and bool(self.table.selectedIndexes()))
        self.show_button.setEnabled(bool(self.table.selectedIndexes()))
        self.compare_button.setEnabled(len(self._selected()) == 2)

    def _on_busy(self, busy: bool) -> None:
        if busy:
            # Moving, with no figure, until something says how far along
            # it is: a backend that cannot say would otherwise show a
            # bar stuck at nothing for as long as programming took.
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
            self.progress.setFormat("")
        self._enable()

    def _on_progress(self, label: str, fraction: float) -> None:
        if fraction <= 0.0:
            return  # started, and nothing yet to show for it
        self.progress.setRange(0, 1000)
        self.progress.setValue(round(fraction * 1000))
        # The word as well as the bar: a bar alone does not say which of
        # erasing, programming and verifying it is part way through.
        self.progress.setFormat(f"{label} %p%")

    def _on_finished(self, _name: str, _ok: bool) -> None:
        self._enable()
