# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Tools > pyOCD device packs: find a device, and install the pack that describes it.

From the top down, in the order it is done. The list of every device there
is a pack for is fetched, once; a part is looked up in it, as it is typed,
since the list is on this computer by then; its pack is installed; and the
device is chosen as the target. Below that are the packs already here.

The dialog only asks. ``PackManager`` does the work, on a thread of its own,
so the dialog can be closed while a pack is still coming down: the Event
Log says when it has arrived.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.backends.pyocd_packs import MOST_FOUND, Device, Pack
from pyflashgui.core.context import Context
from pyflashgui.core.pack_manager import PackManager
from pyflashgui.ui import folders, messages

INTRODUCTION = (
    "pyOCD knows some devices by itself. The rest are described by CMSIS-Packs, which the "
    "makers of the devices publish. Find a device here and install its pack, and the device "
    "is in the list of targets from then on. J-Link Commander has its own list of devices and "
    "needs none of this."
)
NEVER_FETCHED = (
    "The list of devices has not been fetched yet. Fetch it to look a device up, or add a "
    "pack from a file."
)
FETCH = "Fetch the list"
UPDATE = "Update the list"
#: How long after the last letter typed the search is made.
TYPING_MS = 250
NOTHING_FOUND = (
    "No device has that in its name. If it is a new one, update the list: it may have been "
    "added since."
)
FIND_TIP = (
    "Any part of the device's part number, in any case. The search is of\n"
    "the list on this computer, and is made as you type."
)
UPDATE_TIP = (
    "Download the list of every device there is a pack for. It is a few\n"
    "megabytes and takes a little while. Needed once, and after that only\n"
    "for a device newer than the list."
)
INSTALL_TIP = "Download the pack the selected device is in. Every device in it comes with it."
USE_TIP = "Choose the selected device as the target, in the bar across the top of the window."
ADD_FILE_TIP = (
    "Add a pack downloaded by hand from its maker's website, as a .pack\n"
    "file: for a computer that cannot reach the internet. A copy is kept,\n"
    "so the file can be moved or deleted afterwards."
)
PACK_FILES = "CMSIS-Pack (*.pack);;All files (*)"
REMOVE_TIP = (
    "Delete the selected pack from this computer. Its devices leave the\n"
    "list of targets; it can be installed again."
)


#: Between one column and the next, beyond what the text itself needs.
GAP = 16


def fetched_text(when: datetime | None) -> str:
    if when is None:
        return NEVER_FETCHED
    return f"The list of devices was fetched on {when:%d %B %Y}."


class PacksDialog(QDialog):
    #: A device was chosen as the target: its name as pyOCD has it.
    chosen = Signal(str)

    def __init__(
        self,
        manager: PackManager,
        parent: QWidget | None = None,
        ctx: Context | None = None,
    ) -> None:
        super().__init__(parent)
        #: For remembering where packs are added from. None leaves that
        #: to the file dialog.
        self.ctx = ctx
        self.setWindowTitle("pyOCD device packs")
        self.manager = manager
        self.resize(680, 560)
        #: Typing is not searching until it stops for a moment.
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(TYPING_MS)
        self._typing.timeout.connect(self.find)
        self._never_fetched = True
        #: Whether there is anything to search: the list, or a pack added
        #: from a file, which needs no list.
        self._searchable = False

        introduction = QLabel(INTRODUCTION)
        introduction.setWordWrap(True)

        self.text = QLineEdit()
        self.text.setPlaceholderText("Part of a device's part number")
        self.text.setToolTip(FIND_TIP)
        self.text.setAccessibleName("Device")
        self.text.setClearButtonEnabled(True)

        self.devices = QTreeWidget()
        self.devices.setHeaderLabels(["Device", "Maker", "Pack", "Version", "Installed"])
        self.devices.setRootIsDecorated(False)
        self.devices.setSelectionMode(QAbstractItemView.SingleSelection)
        self.devices.setAccessibleName("Devices found")
        self.result = QLabel()
        self.result.setWordWrap(True)

        self.install_button = QPushButton("Install pack")
        self.install_button.setToolTip(INSTALL_TIP)
        self.use_button = QPushButton("Use as target")
        self.use_button.setToolTip(USE_TIP)

        self.packs = QTreeWidget()
        self.packs.setHeaderLabels(["Pack", "Version", "From"])
        self.packs.setRootIsDecorated(False)
        self.packs.setSelectionMode(QAbstractItemView.SingleSelection)
        self.packs.setAccessibleName("Installed packs")
        self.add_file_button = QPushButton("Add from file...")
        self.add_file_button.setToolTip(ADD_FILE_TIP)
        self.remove_button = QPushButton("Remove...")
        self.remove_button.setToolTip(REMOVE_TIP)

        self.fetched = QLabel()
        self.update_button = QPushButton(FETCH)
        self.update_button.setToolTip(UPDATE_TIP)

        self.status = QLabel()
        self.status.setWordWrap(True)
        #: Back and forth rather than a fraction: a pack is one file, and
        #: how much of it has arrived is not something the library says.
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)

        closer = QDialogButtonBox(QDialogButtonBox.Close)
        closer.rejected.connect(self.reject)
        # Enter in the search box searches, and must not also be Close.
        closer.button(QDialogButtonBox.Close).setAutoDefault(False)
        for button in (
            self.install_button,
            self.use_button,
            self.remove_button,
            self.add_file_button,
            self.update_button,
        ):
            button.setAutoDefault(False)

        found_row = QHBoxLayout()
        found_row.addWidget(self.install_button)
        found_row.addWidget(self.use_button)
        found_row.addStretch(1)
        packs_row = QHBoxLayout()
        packs_row.addWidget(self.add_file_button)
        packs_row.addWidget(self.remove_button)
        packs_row.addStretch(1)
        list_row = QHBoxLayout()
        list_row.addWidget(self.fetched, 1)
        list_row.addWidget(self.update_button)

        layout = QVBoxLayout(self)
        layout.addWidget(introduction)
        layout.addLayout(list_row)
        layout.addWidget(self.text)
        layout.addWidget(self.devices, 3)
        layout.addWidget(self.result)
        layout.addLayout(found_row)
        layout.addWidget(QLabel("Installed on this computer:"))
        layout.addWidget(self.packs, 2)
        layout.addLayout(packs_row)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addWidget(closer)

        self.text.textChanged.connect(lambda _text: self._typing.start())
        self.text.returnPressed.connect(self.find)
        self.install_button.clicked.connect(self._install)
        self.use_button.clicked.connect(self._use)
        self.remove_button.clicked.connect(self._remove)
        self.add_file_button.clicked.connect(self._add_file)
        self.update_button.clicked.connect(manager.fetch_list)
        self.devices.itemSelectionChanged.connect(self._enable)
        self.devices.itemDoubleClicked.connect(lambda *_: self._use())
        self.packs.itemSelectionChanged.connect(self._enable)
        manager.found.connect(self._show_devices)
        manager.not_found.connect(self._not_found)
        manager.listed.connect(self._show_packs)
        manager.progress.connect(self.status.setText)
        manager.busy_changed.connect(self._on_busy)

        self._on_busy(manager.busy)
        manager.refresh()
        (self.text if self._searchable else self.update_button).setFocus()

    # --- what is selected ------------------------------------------------------------
    def selected_device(self) -> Device | None:
        item = self.devices.currentItem()
        return None if item is None else item.data(0, Qt.UserRole)

    def selected_pack(self) -> Pack | None:
        item = self.packs.currentItem()
        return None if item is None else item.data(0, Qt.UserRole)

    # --- finding ---------------------------------------------------------------------
    def find(self) -> None:
        """Search the list for what is typed. Nothing typed is nothing found."""
        self._typing.stop()
        if not self._searchable:
            return
        if not self.text.text().strip():
            self.devices.clear()
            self.result.setText("")
            self._enable()
            return
        self.manager.find(self.text.text())

    def _show_devices(self, devices: list[Device]) -> None:
        kept = self.selected_device()
        self.devices.clear()
        for device in devices[:MOST_FOUND]:
            item = QTreeWidgetItem(
                [
                    device.name,
                    device.vendor,
                    device.pack.label,
                    device.pack.version,
                    "Yes" if device.installed else "",
                ]
            )
            item.setData(0, Qt.UserRole, device)
            self.devices.addTopLevelItem(item)
            if kept is not None and device.name == kept.name:
                self.devices.setCurrentItem(item)
        for column in range(self.devices.columnCount()):
            self.devices.resizeColumnToContents(column)
            self.devices.setColumnWidth(column, self.devices.columnWidth(column) + GAP)
        if self.devices.currentItem() is None and devices:
            self.devices.setCurrentItem(self.devices.topLevelItem(0))
        if not devices:
            self.result.setText(NOTHING_FOUND)
        elif len(devices) > MOST_FOUND:
            self.result.setText(
                f"{len(devices)} devices have that in their name; the first {MOST_FOUND} are "
                "shown. More of the name finds fewer."
            )
        else:
            self.result.setText(f"{len(devices)} found." if len(devices) > 1 else "1 found.")
        self._enable()

    def _not_found(self, why: str) -> None:
        self.devices.clear()
        self.result.setText(why)
        self._enable()

    # --- what is installed -----------------------------------------------------------
    def _show_packs(self, packs: list[Pack], fetched: datetime | None) -> None:
        self._never_fetched = fetched is None
        self._searchable = not self._never_fetched or any(pack.file for pack in packs)
        self.fetched.setText(fetched_text(fetched))
        self.packs.clear()
        for pack in packs:
            item = QTreeWidgetItem(
                [pack.label, pack.version, "a file" if pack.file else "download"]
            )
            item.setData(0, Qt.UserRole, pack)
            self.packs.addTopLevelItem(item)
        self.packs.resizeColumnToContents(0)
        self.packs.setColumnWidth(0, self.packs.columnWidth(0) + GAP)
        self._enable()
        # What was found says which of it is installed, and that has changed;
        # and a list that has just arrived is one to search.
        if not self.manager.busy:
            self.find()

    def _install(self) -> None:
        if (device := self.selected_device()) is None:
            return
        pack = device.pack
        where = f" from {pack.url}" if pack.url else ""
        asked = messages.question(
            self,
            f"Download {pack}?",
            f"It is downloaded{where}, and kept on this computer for pyOCD to use. A pack "
            "holds every device of its family, and can be tens of megabytes.",
            messages.Button.Yes | messages.Button.No,
            messages.Button.Yes,
        )
        if asked == messages.Button.Yes:
            self.manager.install(pack)

    def _remove(self) -> None:
        if (pack := self.selected_pack()) is None:
            return
        asked = messages.question(
            self,
            f"Remove {pack}?",
            "Its devices leave the list of targets. "
            + (
                "It can be added from its file again."
                if pack.file
                else "It can be installed again."
            ),
            messages.Button.Yes | messages.Button.No,
            messages.Button.No,
        )
        if asked == messages.Button.Yes:
            self.manager.remove(pack)

    def _add_file(self) -> None:
        caption = "Add a CMSIS-Pack"
        if self.ctx is not None:
            path = folders.open_file(self, self.ctx, folders.PACK, caption, PACK_FILES, Path.home())
        else:
            path, _type = QFileDialog.getOpenFileName(self, caption, str(Path.home()), PACK_FILES)
        if path:
            self.manager.add_file(path)

    def _use(self) -> None:
        device = self.selected_device()
        if device is not None and device.installed:
            self.chosen.emit(device.name.lower())
            self.status.setText(f"{device.name.lower()} is the target.")

    # --- what can be pressed ---------------------------------------------------------
    def _on_busy(self, busy: bool) -> None:
        self.bar.setVisible(busy)
        self._enable()

    def _enable(self) -> None:
        busy = self.manager.busy
        device = self.selected_device()
        self.install_button.setEnabled(not busy and device is not None and not device.installed)
        self.use_button.setEnabled(device is not None and device.installed)
        self.remove_button.setEnabled(not busy and self.selected_pack() is not None)
        self.update_button.setEnabled(not busy)
        self.add_file_button.setEnabled(not busy)
        self.update_button.setText(FETCH if self._never_fetched else UPDATE)
        # Nothing to search until there is a list, or a pack from a file.
        self.text.setEnabled(self._searchable)
