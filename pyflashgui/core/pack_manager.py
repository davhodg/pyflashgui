# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Finding, installing and removing CMSIS-Packs without the window waiting.

``backends.pyocd_packs`` does the work and blocks while it does. This runs
one piece of it at a time on a thread of its own and says how it went, in
the Event Log and through signals, so that the dialog asking can be closed
while a pack is still coming down.

Not the probe's worker: a download has nothing to do with a probe, and
should neither wait for one nor keep one waiting. And a plain daemon thread
rather than a QThread, because a download cannot be told to stop: closing
pyflashgui in the middle of one must not wait for it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from pyflashgui.backends import pyocd_packs
from pyflashgui.backends.base import BackendError
from pyflashgui.backends.pyocd_packs import Pack
from pyflashgui.core.events import EventLog


class PackManager(QObject):
    #: Something is being fetched, or has finished.
    busy_changed = Signal(bool)
    #: What is being done, in words, as it goes.
    progress = Signal(str)
    #: The devices a search found, as a list of Device.
    found = Signal(list)
    #: A search could not be made: why.
    not_found = Signal(str)
    #: The packs installed, as a list of Pack, and when the list of devices
    #: was fetched (a datetime, or None).
    listed = Signal(list, object)
    #: A pack was installed or removed: the targets are not what they were.
    changed = Signal()

    _delivered = Signal(object)

    def __init__(self, events: EventLog, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.events = events
        self.busy = False
        self._shut = False
        self._delivered.connect(self._deliver)

    # --- running things --------------------------------------------------------------
    def _run(self, doing: str, work: Callable[[], Any], done: Callable[[Any], None]) -> bool:
        if self.busy:
            self.events.warning(f"{doing} was not started: a download is still running.")
            return False
        self._set_busy(True)
        self.progress.emit(f"{doing}...")

        def job() -> None:
            try:
                packet = (done, work(), None)
            except BackendError as exc:
                packet = (done, None, str(exc))
            except Exception as exc:  # report, never die
                packet = (done, None, f"{doing} failed: {type(exc).__name__}: {exc}")
            try:
                self._delivered.emit(packet)
            except RuntimeError:  # the window went while it was running
                pass

        threading.Thread(target=job, name="packs", daemon=True).start()
        return True

    @Slot(object)
    def _deliver(self, packet: tuple) -> None:
        if self._shut:
            return
        done, result, error = packet
        self._set_busy(False)
        if error is not None:
            self.events.error(error)
            self.progress.emit(error)
        else:
            done(result)
        self.refresh()

    def _set_busy(self, busy: bool) -> None:
        if busy != self.busy:
            self.busy = busy
            self.busy_changed.emit(busy)

    def _tick(self, doing: str) -> pyocd_packs.Tick:
        def tick(arrived: int, total: int | None) -> None:
            of = f" of {total}" if total else ""
            try:
                self.progress.emit(f"{doing}: {arrived}{of}...")
            except RuntimeError:
                pass

        return tick

    # --- what can be asked for -------------------------------------------------------
    def refresh(self) -> None:
        """Say again what is installed. Quick: nothing is downloaded."""
        try:
            self.listed.emit(pyocd_packs.installed(), pyocd_packs.list_fetched())
        except Exception as exc:
            self.events.error(f"Listing the installed packs failed: {exc}")

    def find(self, text: str) -> None:
        """Look for devices by part of their name. Quick: the list is on this computer."""
        try:
            self.found.emit(pyocd_packs.find(text))
        except BackendError as exc:
            self.not_found.emit(str(exc))

    def fetch_list(self) -> None:
        doing = "Fetching the list of devices"

        def done(count: int) -> None:
            message = f"Fetched the list of devices: {count} of them."
            self.events.good(message)
            self.progress.emit(message)

        self._run(doing, lambda: pyocd_packs.fetch_list(self._tick(doing)), done)

    def install(self, pack: Pack) -> None:
        doing = f"Downloading {pack}"

        def done(_result) -> None:
            message = f"Installed {pack}. Its devices are in the list of targets."
            self.events.good(message)
            self.progress.emit(message)
            self.changed.emit()

        self._run(doing, lambda: pyocd_packs.install(pack, self._tick(doing)), done)

    def add_file(self, path: str) -> None:
        """Keep a .pack file that was downloaded by hand, and use its devices."""
        name = Path(path).name

        def done(result: tuple[Pack, int]) -> None:
            pack, count = result
            devices = "1 device" if count == 1 else f"{count} devices"
            message = f"Added {pack} from {name}: {devices}, now in the list of targets."
            self.events.good(message)
            self.progress.emit(message)
            self.changed.emit()

        self._run(f"Adding {name}", lambda: pyocd_packs.add_file(path), done)

    def remove(self, pack: Pack) -> None:
        if self.busy:
            self.events.warning(f"{pack} was not removed: a download is still running.")
            return
        try:
            pyocd_packs.remove(pack)
        except BackendError as exc:
            self.events.error(str(exc))
        else:
            message = f"Removed {pack}."
            self.events.information(message)
            self.progress.emit(message)
            self.changed.emit()
        self.refresh()

    # --- going away ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Stop listening. A download still running is left to end with the process."""
        self._shut = True
