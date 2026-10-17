# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Tools > pyOCD device packs: find a device, and install the pack that describes it.

From the top down, in the order it is done. The list of every device there
is a pack for is fetched, once, and shown whole; typing narrows it, which is
instant since the list is on this computer by then; the pack a device is in
is installed; and the device is chosen as the target. Below that are the
packs already here.

Each pack's address is shown with it: a computer that cannot reach the
internet is given the file by hand, downloaded from there on one that can.

The dialog only asks. ``PackManager`` does the work, on a thread of its own,
so the dialog can be closed while a pack is still coming down: the Event
Log says when it has arrived.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.backends.pyocd_packs import Device, Pack
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
NOTHING_FOUND = (
    "No device has that in its name. If it is a new one, update the list: it may have been "
    "added since."
)
FIND_TIP = "Any part of the device's part number, in any case. The list narrows\nas you type."
COPY_TIP = "Copy the address, to download the pack by hand: for a computer with no internet."
DEVICE_COLUMNS = ["Device", "Maker", "Pack", "Version", "Installed"]
UPDATE_TIP = (
    "Download the list of every device there is a pack for. It is a few\n"
    "megabytes and takes a little while. Needed once, and after that only\n"
    "for a device newer than the list."
)
INSTALL_TIP = "Download the pack the selected device is in. Every device in it comes with it."
USE_TIP = "Choose the selected device as the target, in the bar across the top of the window."
ADD_FILE_TIP = (
    "Add a pack downloaded by hand, as a .pack file: for a computer that\n"
    "cannot reach the internet. Where each pack is downloaded from is shown\n"
    "under the list when one of its devices is selected; Copy address takes\n"
    "it to another computer. A copy of the file is kept here, so it can be\n"
    "moved or deleted afterwards."
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
        self.resize(860, 640)
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

        #: Every device, whatever is typed; the view shows what the filter lets
        #: through. Narrowing thousands of rows is a filter's job, not a
        #: rebuild's.
        self.model = QStandardItemModel(0, len(DEVICE_COLUMNS), self)
        self.model.setHorizontalHeaderLabels(DEVICE_COLUMNS)
        self.shown = QSortFilterProxyModel(self)
        self.shown.setSourceModel(self.model)
        self.shown.setFilterKeyColumn(0)
        self.shown.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.devices = QTreeView()
        self.devices.setModel(self.shown)
        self.devices.setRootIsDecorated(False)
        self.devices.setUniformRowHeights(True)  # thousands of rows, all one line
        self.devices.setSelectionMode(QAbstractItemView.SingleSelection)
        self.devices.setAccessibleName("Devices")
        self.result = QLabel()
        self.result.setWordWrap(True)
        #: Where the selected device's pack comes from, to be copied.
        self.address = QLabel()
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.address.setWordWrap(True)
        self.copy_button = QPushButton("Copy address")
        self.copy_button.setToolTip(COPY_TIP)

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
            self.copy_button,
        ):
            button.setAutoDefault(False)

        address_row = QHBoxLayout()
        address_row.addWidget(self.address, 1)
        address_row.addWidget(self.copy_button)
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
        layout.addLayout(address_row)
        layout.addLayout(found_row)
        layout.addWidget(QLabel("Installed on this computer:"))
        layout.addWidget(self.packs, 2)
        layout.addLayout(packs_row)
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        layout.addWidget(closer)

        self.text.textChanged.connect(lambda _text: self.find())
        self.copy_button.clicked.connect(self._copy_address)
        self.install_button.clicked.connect(self._install)
        self.use_button.clicked.connect(self._use)
        self.remove_button.clicked.connect(self._remove)
        self.add_file_button.clicked.connect(self._add_file)
        self.update_button.clicked.connect(manager.fetch_list)
        self.devices.selectionModel().currentChanged.connect(lambda *_: self._on_device())
        self.devices.doubleClicked.connect(lambda *_: self._use())
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
        index = self.devices.currentIndex()
        if not index.isValid():
            return None
        row = self.shown.mapToSource(index).row()
        return self.model.item(row, 0).data(Qt.UserRole)

    def shown_names(self) -> list[str]:
        """The devices the list shows now, top to bottom."""
        return [self.shown.index(row, 0).data() for row in range(self.shown.rowCount())]

    def selected_pack(self) -> Pack | None:
        item = self.packs.currentItem()
        return None if item is None else item.data(0, Qt.UserRole)

    # --- finding ---------------------------------------------------------------------
    def find(self) -> None:
        """Narrow the list to what is typed. Nothing typed is every device."""
        self.shown.setFilterFixedString("".join(self.text.text().split()))
        if self.devices.currentIndex().isValid() is False and self.shown.rowCount():
            self.devices.setCurrentIndex(self.shown.index(0, 0))
        self._say_how_many()
        self._on_device()

    def _say_how_many(self) -> None:
        total, shown = self.model.rowCount(), self.shown.rowCount()
        if not total:
            self.result.setText("")
        elif not shown:
            self.result.setText(NOTHING_FOUND)
        elif shown == total:
            self.result.setText(f"{total} devices.")
        else:
            self.result.setText(f"{shown} of {total} devices.")

    def _show_devices(self, devices: list[Device]) -> None:
        """Every device, in the model the filter narrows."""
        kept = self.selected_device()
        self.devices.setUpdatesEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        for device in devices:
            row = [
                QStandardItem(text)
                for text in (
                    device.name,
                    device.vendor,
                    device.pack.label,
                    device.pack.version,
                    "Yes" if device.installed else "",
                )
            ]
            for item in row:
                item.setEditable(False)
            row[0].setData(device, Qt.UserRole)
            self.model.appendRow(row)
        self.devices.setUpdatesEnabled(True)
        # Measured from the longest text in each column rather than by the
        # view, which would measure every one of thousands of rows to find it.
        metrics = self.devices.fontMetrics()
        header = self.devices.header()
        for column, title in enumerate(DEVICE_COLUMNS):
            texts = [self.model.item(row, column).text() for row in range(self.model.rowCount())]
            longest = max([title, *texts], key=len)
            width = max(metrics.horizontalAdvance(longest), header.sectionSizeHint(column))
            self.devices.setColumnWidth(column, width + GAP)
        # The one selected before, if it is still shown.
        if kept is not None:
            for row in range(self.shown.rowCount()):
                if self.shown.index(row, 0).data() == kept.name:
                    self.devices.setCurrentIndex(self.shown.index(row, 0))
                    break
        self.find()

    def _not_found(self, why: str) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self.result.setText(why)
        self._on_device()

    def _on_device(self) -> None:
        """Say where the selected device's pack comes from."""
        device = self.selected_device()
        if device is None:
            self.address.setText("")
        elif device.pack.file:
            self.address.setText(f"Added from a file, kept as {device.pack.file}")
        elif device.pack.address:
            self.address.setText(f"Downloaded from {device.pack.address}")
        else:
            self.address.setText("The list does not say where this pack is downloaded from.")
        self._enable()

    def _copy_address(self) -> None:
        if (device := self.selected_device()) is not None and device.pack.address:
            QApplication.clipboard().setText(device.pack.address)
            self.status.setText(f"Copied {device.pack.address}")

    # --- what is installed -----------------------------------------------------------
    def _show_packs(self, packs: list[Pack], fetched: datetime | None) -> None:
        self._never_fetched = fetched is None
        self._searchable = not self._never_fetched or any(pack.file for pack in packs)
        self.fetched.setText(fetched_text(fetched))
        self.packs.clear()
        for pack in packs:
            item = QTreeWidgetItem(
                [pack.label, pack.version, "A file added by hand" if pack.file else pack.address]
            )
            item.setToolTip(2, pack.file or pack.address)
            item.setData(0, Qt.UserRole, pack)
            self.packs.addTopLevelItem(item)
        for column in (0, 1):
            self.packs.resizeColumnToContents(column)
            self.packs.setColumnWidth(column, self.packs.columnWidth(column) + GAP)
        self._enable()
        # Every device again: which are installed has changed, and a list
        # that has just arrived is one to show.
        if not self.manager.busy and self._searchable:
            self.manager.find("")

    def _install(self) -> None:
        if (device := self.selected_device()) is None:
            return
        pack = device.pack
        where = f" from {pack.address}" if pack.address else ""
        asked = messages.question(
            self,
            f"Download {pack}?",
            f"It is downloaded{where}, and kept on this computer for pyOCD to use. A pack "
            "holds every device of its family, and can be over a hundred megabytes.",
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
        device = self.selected_device()
        self.copy_button.setEnabled(device is not None and bool(device.pack.address))
