# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Files pane: what is to be programmed, and the buttons that do it.

A list of firmware files, each ticked or not, and Erase, Program, Verify and
Reset beside it. The list is kept in the workspace, so that programming a
product is choosing its workspace and pressing Program.

**A file is read again every time it is used.** It is what a build has just
written, and a list that programmed what the file held when it was added
would program yesterday's firmware without a word. The file is watched as
well, so the sizes and the memory map on screen follow each build.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.backends.base import ERASE_CHIP, ERASE_SECTORS
from pyflashgui.core import images
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher, size_text
from pyflashgui.core.images import Image, ImageError
from pyflashgui.core.memory_map import lay_out
from pyflashgui.ui import folders, fonts
from pyflashgui.ui.confirm import Confirmations
from pyflashgui.ui.erase_dialog import EraseDialog
from pyflashgui.ui.persist import remember

FILES_KEY = "files.list"

FILE, FORMAT, ADDRESS, SIZE = range(4)
HEADINGS = ("File", "Format", "Address", "Size")

ADDRESS_TIP = (
    "Where a raw binary starts. It carries no addresses of its own, so it\n"
    "cannot be programmed until it is given one, in hexadecimal. A file that\n"
    "has its own addresses shows where its first byte goes."
)
#: How long after a file changes it is read again. A linker writes a file in
#: pieces, and reading it between two of them reads half a file.
SETTLE_MS = 300


@dataclass
class Entry:
    """One file in the list, and what reading it last found."""

    path: str
    #: Where a raw binary starts, typed in. None until it has been.
    address: int | None = None
    enabled: bool = True
    image: Image | None = None
    #: Why it could not be read, when it could not.
    problem: str = ""

    def read(self) -> None:
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


class FilesView(QWidget):
    #: The files, or what is in one of them, changed: the memory map is out
    #: of date.
    changed = Signal()
    #: Read... was pressed: the window asks what to read and reads it.
    read_requested = Signal()

    def __init__(self, flasher: Flasher, ctx: Context, confirm: Confirmations) -> None:
        super().__init__()
        self.flasher = flasher
        self.ctx = ctx
        self.confirm = confirm
        self.entries: list[Entry] = []
        self._filling = False

        self.table = QTableWidget(0, len(HEADINGS))
        self.table.setHorizontalHeaderLabels(HEADINGS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAccessibleName("Files to program")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(FILE, QHeaderView.Stretch)
        for column in (FORMAT, ADDRESS, SIZE):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._enable)

        self.add_button = QPushButton("Add...")
        self.add_button.setToolTip("Add firmware files: ELF, Intel HEX, S-record or raw binary.")
        self.add_button.clicked.connect(self._add_dialog)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Take the selected files off the list. The files are kept.")
        self.remove_button.clicked.connect(self.remove_selected)

        self.chip_erase = QCheckBox("Erase everything first")
        self.chip_erase.setToolTip(
            "Erase all of the flash before programming, so that nothing of what\n"
            "was there is left. Without it, only the sectors the files write to\n"
            "are erased, and the rest of the flash is kept."
        )
        self.verify_after = QCheckBox("Verify")
        self.verify_after.setChecked(True)
        self.verify_after.setToolTip(
            "Read the flash back after programming and compare it with the files."
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
        self.program_button.setToolTip("Write the ticked files to the target.")
        self.program_button.clicked.connect(self.program)
        self.verify_button = QPushButton("Verify")
        self.verify_button.setToolTip(
            "Compare what is in the target with the ticked files, changing nothing."
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
            "Read part of the target's memory back and show it in the Memory\n"
            "pane, changing nothing in the target. It can be saved from there."
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
        for widget in (self.add_button, self.remove_button):
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
        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(files_row)
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
            [{"path": e.path, "address": e.address, "enabled": e.enabled} for e in self.entries],
        )

    def _watch(self, path: str) -> None:
        if Path(path).exists() and path not in self._watcher.files():
            self._watcher.addPath(path)

    def add_files(self, paths: list[str]) -> None:
        """Put these files on the list, each once."""
        have = {Path(e.path) for e in self.entries}
        for path in paths:
            if Path(path) in have:
                continue
            have.add(Path(path))
            entry = Entry(path=str(path))
            entry.read()
            self.entries.append(entry)
            self._watch(entry.path)
            if entry.image is not None:
                self.ctx.events.information(f"Added {entry.image.summary()}")
        self._changed()

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            entry = self.entries.pop(row)
            if entry.path in self._watcher.files():
                self._watcher.removePath(entry.path)
        if rows:
            self._changed()

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
            name = QTableWidgetItem(Path(entry.path).name)
            name.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name.setCheckState(Qt.Checked if entry.enabled else Qt.Unchecked)
            name.setToolTip(entry.path)
            image = entry.image
            format_item = QTableWidgetItem(image.format if image else "Not read")
            size = QTableWidgetItem(size_text(image.size) if image else "")
            needs_address = image is None and images.looks_binary(entry.path)
            is_binary = (image is not None and image.format == images.BINARY) or needs_address
            if image is not None:
                address = QTableWidgetItem(f"{image.address:08X}")
            else:
                address = QTableWidgetItem("" if entry.address is None else f"{entry.address:08X}")
            address.setFont(fonts.mono())
            address.setToolTip(ADDRESS_TIP)
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            address.setFlags(flags | Qt.ItemIsEditable if is_binary else flags)
            for item in (format_item, size):
                item.setFlags(flags)
            if entry.problem:
                # In words in the row, and whole in the tooltip: a row that
                # only turned a colour would not say what was wrong with it.
                format_item.setText("Cannot be read")
                for item in (name, format_item, address, size):
                    item.setToolTip(f"{entry.path}\n\n{entry.problem}")
            for column, item in enumerate((name, format_item, address, size)):
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
        """The ticked files as they were last read, for the memory map."""
        return [e.image for e in self.entries if e.enabled and e.image is not None]

    def reread(self) -> list[Image] | None:
        """The ticked files, read now. None, having said why, if one cannot be."""
        ticked = [e for e in self.entries if e.enabled]
        for entry in ticked:
            entry.read()
        self._fill()
        self.changed.emit()
        failed = [e for e in ticked if e.image is None]
        for entry in failed:
            self.ctx.events.error(f"{Path(entry.path).name} cannot be read: {entry.problem}")
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
            self.ctx.events.warning("There is nothing to program: no file is ticked.")
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
                else " in the sectors these files write to."
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
