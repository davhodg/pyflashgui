# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Device packs: finding a device, installing its pack, removing it.

Against a store of packs that is a folder in the test's own directory and an
index made here: nothing is downloaded, and the packs really installed on
the computer running the tests are neither seen nor touched.
"""

import json
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

from pyflashgui.backends import pyocd_packs
from pyflashgui.backends.pyocd_packs import Pack, PackError
from pyflashgui.core.events import ERROR, GOOD, EventLog
from pyflashgui.core.pack_manager import PackManager
from pyflashgui.ui import packs_dialog
from pyflashgui.ui.packs_dialog import PacksDialog

XMC = Pack("Infineon", "XMC4000_DFP", "2.14.0", "https://example.invalid/xmc/")
STM = Pack("Keil", "STM32F4xx_DFP", "3.0.0", "https://example.invalid/stm/")


def entry(name: str, vendor: str, pack: Pack) -> dict:
    return {
        "name": name,
        "vendor": vendor,
        "from_pack": {
            "vendor": pack.vendor,
            "pack": pack.name,
            "version": pack.version,
            "url": pack.url,
        },
    }


INDEX = {
    "XMC4500-F100x1024": entry("XMC4500-F100x1024", "Infineon:7", XMC),
    "XMC4500-F144x768": entry("XMC4500-F144x768", "Infineon:7", XMC),
    "STM32F407VG": entry("STM32F407VG", "STMicroelectronics:13", STM),
}


class Store:
    """What stands in for the internet and for pyOCD's folder of packs."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        #: What a download does instead of arriving, when it is to fail.
        self.fault: Exception | None = None
        #: True for a download that fails without saying so.
        self.silent_fault = False
        self.downloaded: list[str] = []

    def open(self, tick=None):
        return Cache(self, tick)


class Cache:
    def __init__(self, store: Store, tick) -> None:
        self.store, self.tick = store, tick
        self.data_path = str(store.folder)
        self.index_path = str(store.folder / "index.json")

    @property
    def index(self) -> dict:
        try:
            return json.loads(Path(self.index_path).read_text(encoding="utf-8"))
        except OSError:
            return {}

    def cache_descriptors(self) -> None:
        if self.store.fault is not None:
            raise self.store.fault
        if self.tick is not None:
            self.tick(1, 2)
            self.tick(2, 2)
        if not self.store.silent_fault:
            Path(self.index_path).write_text(json.dumps(INDEX), encoding="utf-8")

    def download_pack_list(self, references) -> None:
        if self.store.fault is not None:
            raise self.store.fault
        for reference in references:
            self.store.downloaded.append(str(reference))
            if self.store.silent_fault:
                continue
            file = self.store.folder / reference.get_pack_name()
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"a pack")
            if self.tick is not None:
                self.tick(1, 1)


@pytest.fixture
def store(tmp_path, monkeypatch):
    made = Store(tmp_path / "packs")
    made.folder.mkdir()
    monkeypatch.setattr(pyocd_packs, "open_cache", made.open)
    return made


@pytest.fixture
def fetched(store):
    pyocd_packs.fetch_list()
    return store


def wait_for(done, seconds: float = 5.0) -> None:
    until = time.monotonic() + seconds
    while not done():
        assert time.monotonic() < until, "it never finished"
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()


def said(manager: PackManager, level: str) -> list[str]:
    return [message for message, at in manager.said if at == level]


# --- the work itself ------------------------------------------------------------------
def test_nothing_is_there_before_the_list_is_fetched(store):
    assert pyocd_packs.list_fetched() is None
    assert pyocd_packs.installed() == []
    with pytest.raises(PackError, match="has not been fetched"):
        pyocd_packs.find("xmc")


def test_fetching_the_list_says_how_many_devices_and_how_it_went(store):
    ticks = []
    assert pyocd_packs.fetch_list(lambda arrived, total: ticks.append((arrived, total))) == 3
    assert ticks == [(1, 2), (2, 2)]
    assert pyocd_packs.list_fetched() is not None


def test_a_list_that_did_not_arrive_is_said_to_be_the_network(store):
    store.silent_fault = True
    with pytest.raises(PackError, match="brought nothing back"):
        pyocd_packs.fetch_list()
    store.silent_fault, store.fault = False, OSError("no route")
    with pytest.raises(PackError, match="Fetching the list of devices failed: no route"):
        pyocd_packs.fetch_list()


def test_a_device_is_found_by_any_part_of_its_name_in_any_case(fetched):
    found = pyocd_packs.find(" xmc4500 ")
    assert [d.name for d in found] == ["XMC4500-F100x1024", "XMC4500-F144x768"]
    assert found[0].vendor == "Infineon" and found[0].pack == XMC and not found[0].installed
    assert [d.name for d in pyocd_packs.find("F407")] == ["STM32F407VG"]
    assert pyocd_packs.find("nrf52") == [] and pyocd_packs.find("  ") == []


def test_installing_a_pack_installs_every_device_in_it(fetched):
    pyocd_packs.install(XMC)
    assert fetched.downloaded == ["Infineon.XMC4000_DFP.2.14.0"]
    assert pyocd_packs.installed() == [XMC]
    assert [d.installed for d in pyocd_packs.find("xmc")] == [True, True]
    assert [d.installed for d in pyocd_packs.find("stm")] == [False]


def test_a_pack_that_did_not_arrive_is_an_error_even_when_nothing_said_so(fetched):
    fetched.silent_fault = True
    with pytest.raises(PackError, match=r"was not downloaded from https://example.invalid/xmc/"):
        pyocd_packs.install(XMC)
    fetched.silent_fault, fetched.fault = False, OSError("timed out")
    with pytest.raises(PackError, match=r"Downloading Infineon.XMC4000_DFP 2.14.0 failed"):
        pyocd_packs.install(XMC)
    assert pyocd_packs.installed() == []


def test_removing_a_pack_leaves_it_in_the_list_to_install_again(fetched):
    pyocd_packs.install(XMC)
    pyocd_packs.install(STM)
    pyocd_packs.remove(XMC)
    assert pyocd_packs.installed() == [STM]
    assert [d.installed for d in pyocd_packs.find("xmc")] == [False, False]
    pyocd_packs.remove(XMC)  # twice is once


# --- off the window's thread ----------------------------------------------------------
@pytest.fixture
def manager(app, store):
    made = PackManager(EventLog())
    made.said = []
    made.events.posted.connect(lambda message, level: made.said.append((message, level)))
    yield made
    wait_for(lambda: not made.busy)
    made.shutdown()


def test_the_manager_installs_in_the_background_and_says_so(manager, fetched):
    listed, changed, progress = [], [], []
    manager.listed.connect(lambda packs, when: listed.append(packs))
    manager.changed.connect(lambda: changed.append(True))
    manager.progress.connect(progress.append)

    manager.install(XMC)
    assert manager.busy
    manager.install(STM)  # one at a time
    wait_for(lambda: not manager.busy)

    assert fetched.downloaded == ["Infineon.XMC4000_DFP.2.14.0"]
    assert listed[-1] == [XMC] and changed == [True]
    assert progress[0] == "Downloading Infineon.XMC4000_DFP 2.14.0..."
    assert "Downloading Infineon.XMC4000_DFP 2.14.0: 1 of 1..." in progress
    assert said(manager, GOOD) == [
        "Installed Infineon.XMC4000_DFP 2.14.0. Its devices are in the list of targets."
    ]


def test_a_download_that_fails_is_in_the_event_log_and_changes_nothing(manager, fetched):
    changed = []
    manager.changed.connect(lambda: changed.append(True))
    fetched.fault = OSError("no route")
    manager.install(XMC)
    wait_for(lambda: not manager.busy)
    assert said(manager, ERROR) == ["Downloading Infineon.XMC4000_DFP 2.14.0 failed: no route"]
    assert changed == []


# --- the dialog -----------------------------------------------------------------------
@pytest.fixture
def dialog(manager):
    made = PacksDialog(manager)
    yield made
    made.deleteLater()


def answer(monkeypatch, button) -> list[str]:
    """Answer every question the dialog asks, and keep what was asked."""
    asked = []

    def question(_parent, title, _text, *_buttons):
        asked.append(title)
        return button

    monkeypatch.setattr(packs_dialog.messages, "question", question)
    return asked


def names(tree) -> list[str]:
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_the_list_is_fetched_first_and_then_searched_as_it_is_typed(dialog, manager, store):
    assert dialog.fetched.text() == packs_dialog.NEVER_FETCHED
    assert dialog.update_button.text() == "Fetch the list"
    assert not dialog.text.isEnabled(), "nothing to search yet"

    dialog.update_button.click()
    assert manager.busy and not dialog.update_button.isEnabled()
    wait_for(lambda: not manager.busy)
    assert dialog.fetched.text().startswith("The list of devices was fetched on ")
    assert dialog.update_button.text() == "Update the list" and dialog.text.isEnabled()
    assert store.downloaded == [], "the list, and no pack"

    dialog.text.setText("xmc4500")
    assert names(dialog.devices) == [], "not on every letter"
    wait_for(lambda: dialog.devices.topLevelItemCount() == 2)
    assert names(dialog.devices) == ["XMC4500-F100x1024", "XMC4500-F144x768"]
    assert dialog.result.text() == "2 found."
    assert dialog.install_button.isEnabled() and not dialog.use_button.isEnabled()

    dialog.text.setText("")
    dialog.find()
    assert names(dialog.devices) == [] and dialog.result.text() == ""
    assert not dialog.install_button.isEnabled()


def test_what_was_typed_while_the_list_was_coming_is_searched_when_it_arrives(
    dialog, manager, store
):
    pyocd_packs.fetch_list()
    manager.refresh()
    dialog.text.setText("f407")
    manager.fetch_list()  # Update the list
    wait_for(lambda: not manager.busy)
    assert names(dialog.devices) == ["STM32F407VG"]


def test_workspace_has_open_folder_and_tools_does_not(app, store, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from pyflashgui.ui import workspace_menu
    from pyflashgui.ui.main_window import MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()
    opened = []
    monkeypatch.setattr(workspace_menu.QDesktopServices, "openUrl", opened.append)
    window = MainWindow()
    try:
        window.workspace_menu.folder_action.trigger()
        assert [Path(url.toLocalFile()) for url in opened] == [window.ctx.workspace_dir]
        tools = next(m for m in window.menuBar().actions() if m.text() == "&Tools").menu()
        assert "Open workspace folder" not in [a.text() for a in tools.actions()]
    finally:
        window.close()


def test_a_name_no_device_has_says_to_update_the_list(dialog, fetched):
    dialog.manager.refresh()
    dialog.text.setText("nrf52")
    dialog.find()
    assert names(dialog.devices) == [] and dialog.result.text() == packs_dialog.NOTHING_FOUND
    assert not dialog.install_button.isEnabled()


def test_installing_asks_first_and_then_the_device_can_be_the_target(
    dialog, manager, fetched, monkeypatch
):
    manager.refresh()
    dialog.text.setText("xmc4500")
    dialog.find()

    asked = answer(monkeypatch, QMessageBox.No)
    dialog.install_button.click()
    assert asked == ["Download Infineon.XMC4000_DFP 2.14.0?"] and not manager.busy

    answer(monkeypatch, QMessageBox.Yes)
    dialog.install_button.click()
    wait_for(lambda: not manager.busy)

    assert names(dialog.packs) == ["Infineon.XMC4000_DFP"]
    assert dialog.devices.topLevelItem(0).text(4) == "Yes"
    assert not dialog.install_button.isEnabled() and dialog.use_button.isEnabled()

    chosen = []
    dialog.chosen.connect(chosen.append)
    dialog.use_button.click()
    assert chosen == ["xmc4500-f100x1024"]


def test_removing_asks_first(dialog, manager, fetched, monkeypatch):
    pyocd_packs.install(XMC)
    manager.refresh()
    assert names(dialog.packs) == ["Infineon.XMC4000_DFP"]
    dialog.packs.setCurrentItem(dialog.packs.topLevelItem(0))

    answer(monkeypatch, QMessageBox.No)
    dialog.remove_button.click()
    assert pyocd_packs.installed() == [XMC]

    asked = answer(monkeypatch, QMessageBox.Yes)
    dialog.remove_button.click()
    assert asked == ["Remove Infineon.XMC4000_DFP 2.14.0?"]
    assert pyocd_packs.installed() == [] and names(dialog.packs) == []


# --- in the window --------------------------------------------------------------------
def test_tools_has_device_packs_and_a_device_chosen_there_is_the_target(
    app, store, tmp_path, monkeypatch
):
    from PySide6.QtCore import QSettings

    from pyflashgui.ui.main_window import MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path / "home"))
    QSettings().clear()
    window = MainWindow()
    try:
        assert window.packs_action.text() == "pyOCD device packs..."
        window._use_target("xmc4500-f100x1024")
        assert window.probe_bar.chosen_target() == "xmc4500-f100x1024"
    finally:
        window.close()
