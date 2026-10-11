# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The one thing in the window that talks to a backend.

Every call to a backend blocks, and programming blocks for as long as it
takes, so none of them is made from the GUI thread. They are queued on one
worker and run one at a time, which is also what a probe wants: it is one
piece of hardware and does one thing at a time.

What comes back arrives as signals, on the GUI thread, and as lines in the
Event Log. A pane asks for something to be done and listens; it never holds a
connection of its own, so two panes cannot be talking to the same probe.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QObject, Signal

from pyflashgui import backends
from pyflashgui.backends.base import (
    ERASE_SECTORS,
    Backend,
    BackendError,
    CancelledError,
    Connection,
    Verification,
)
from pyflashgui.core import images
from pyflashgui.core.events import EventLog
from pyflashgui.core.images import Image, ImageError, Segment
from pyflashgui.core.memory_map import Region
from pyflashgui.core.worker import Worker

#: Progress is passed on when it has moved this far, and not otherwise: a
#: library reporting every page would otherwise queue a thousand signals to
#: move a bar a thousand times by less than a pixel.
PROGRESS_STEP = 0.01


def size_text(count: int) -> str:
    """A number of bytes as somebody would say it: 512 bytes, 12.5 KiB, 2.0 MiB."""
    if count < 1024:
        return "1 byte" if count == 1 else f"{count} bytes"
    if count < 1024 * 1024:
        return f"{count / 1024:.1f} KiB"
    return f"{count / (1024 * 1024):.1f} MiB"


def verification_text(result: Verification) -> str:
    """What verifying found, in a sentence."""
    if result.ok:
        return f"Verified: {size_text(result.checked)} match the files."
    address, wanted, found = result.first
    count = "1 byte differs" if result.different == 1 else f"{result.different} bytes differ"
    return (
        f"Verify failed: {count} of {result.checked}. The first is at {address:08X}, "
        f"where the file has {wanted:02X} and the target has {found:02X}."
    )


class Flasher(QObject):
    #: The probes plugged in, as a list of ProbeInfo, after ``refresh_probes``.
    probes_changed = Signal(list)
    #: The targets the backend has, as a list of TargetInfo.
    targets_changed = Signal(list)
    #: Connected, or not any more.
    connection_changed = Signal(bool)
    #: Something is being done, or has finished. Nothing else can be asked
    #: for in between.
    busy_changed = Signal(bool)
    #: What is being done, and how far along it is from 0.0 to 1.0.
    progress = Signal(str, float)
    #: The memory of the target in question is known, or has changed.
    regions_changed = Signal()
    #: An operation ended: its name, and whether it did what was asked.
    finished = Signal(str, bool)

    def __init__(
        self,
        events: EventLog,
        backend: str = backends.DEFAULT,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.events = events
        self.backend: Backend = backends.get(backend)
        self.connection: Connection | None = None
        #: What is connected to, while something is: the target's name and
        #: the probe's id.
        self.target = ""
        self.probe = ""
        #: The memory of the target last asked about, connected or not.
        self.regions: list[Region] = []
        self._regions_for = ""
        self.busy = False
        self._cancel = threading.Event()
        self._worker = Worker(self)
        self._last_progress = -1.0
        self._shut = False

    # --- running things --------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.connection is not None

    def _run(
        self,
        name: str,
        work: Callable[[], Any],
        done: Callable[[Any], None],
        quiet: bool = False,
    ) -> bool:
        """Queue ``work`` for the worker, and ``done`` for its result.

        ``quiet`` is for looking things up, which is not something being done
        to a target: it does not mark the flasher busy, so the buttons stay
        as they are, and it may be asked for while something else runs.
        Returns False, having said why, if it could not be started.
        """
        if not quiet:
            if self.busy:
                self.events.warning(f"{name} was not started: something else is still running.")
                return False
            self._set_busy(True)
            self._cancel.clear()
            self._last_progress = -1.0

        def job() -> tuple[Any, str | None, bool]:
            # A backend's own error is a sentence already and is passed on as
            # one. Anything else is a fault in pyflashgui or in a library,
            # and says what kind it was.
            try:
                return work(), None, False
            except CancelledError as exc:
                return None, str(exc), True
            except BackendError as exc:
                return None, str(exc), False

        def deliver(result, error: str | None) -> None:
            cancelled = False
            if error is None:
                result, error, cancelled = result
            if not quiet:
                self._set_busy(False)
            if error is not None:
                (self.events.warning if cancelled else self.events.error)(error)
                if not quiet:
                    self.finished.emit(name, False)
                return
            ok = done(result)
            if not quiet:
                self.finished.emit(name, ok is not False)

        self._worker.submit(job, deliver)
        return True

    def _set_busy(self, busy: bool) -> None:
        if busy != self.busy:
            self.busy = busy
            self.busy_changed.emit(busy)

    def _progress(self, label: str) -> Callable[[float], None]:
        """A progress callback for the worker thread, saying this is what is done.

        Emitting a signal from another thread is the one thing here that is
        safe to do from it: Qt queues it for the GUI thread.
        """

        def report(fraction: float) -> None:
            fraction = max(0.0, min(1.0, float(fraction)))
            if fraction >= 1.0 or fraction - self._last_progress >= PROGRESS_STEP:
                self._last_progress = fraction if fraction < 1.0 else -1.0
                self.progress.emit(label, fraction)

        return report

    def cancel(self) -> None:
        """Ask whatever is running to stop, if it is something that can."""
        self._cancel.set()

    # --- what is there ---------------------------------------------------------------
    def set_backend(self, name: str) -> None:
        """Use another backend. Whatever was connected is let go of first."""
        if name == self.backend.name:
            return
        if self.connected:
            self.disconnect()
        self.backend = backends.get(name)
        self.regions, self._regions_for = [], ""
        self.regions_changed.emit()
        self.refresh_targets()
        self.refresh_probes()

    def refresh_probes(self) -> None:
        backend = self.backend
        self._run("Looking for probes", backend.probes, self.probes_changed.emit, quiet=True)

    def refresh_targets(self) -> None:
        backend = self.backend
        self._run("Listing targets", backend.targets, self.targets_changed.emit, quiet=True)

    def set_target(self, target: str) -> None:
        """Find out the memory of this target, as far as can be told unconnected."""
        if self.connected or target == self._regions_for:
            return
        self._regions_for = target
        backend = self.backend

        def known(regions: list[Region]) -> None:
            # Asked for and answered on different turns of the loop: a
            # target picked since, or a connection made, has the say.
            if not self.connected and self._regions_for == target:
                self.regions = regions
                self.regions_changed.emit()

        self._run("Reading the target's memory map", lambda: backend.regions(target), known, True)

    # --- connecting ------------------------------------------------------------------
    def connect_to(
        self,
        probe: str,
        target: str,
        frequency: int | None = None,
        interface: str | None = None,
    ) -> None:
        backend = self.backend

        def work() -> tuple[Connection, list[Region]]:
            connection = backend.connect(probe, target, frequency, interface)
            try:
                return connection, connection.regions()
            except Exception:
                connection.close()
                raise

        def done(result: tuple[Connection, list[Region]]) -> None:
            self.connection, self.regions = result
            self.probe, self.target = probe, target
            self._regions_for = target
            self.events.good(f"Connected to {target} through probe {probe}.")
            self.connection_changed.emit(True)
            self.regions_changed.emit()

        if not self._run(f"Connecting to {target}", work, done):
            return
        self.events.information(f"Connecting to {target} through probe {probe}...")

    def disconnect(self) -> None:
        connection, self.connection = self.connection, None
        if connection is None:
            return
        target = self.target
        self.connection_changed.emit(False)
        self._run(
            "Disconnecting",
            connection.close,
            lambda _r: self.events.information(f"Disconnected from {target}."),
            quiet=True,
        )

    def _connection(self, name: str) -> Connection | None:
        if self.connection is None:
            self.events.warning(f"{name} needs a probe connected to a target first.")
        return self.connection

    # --- what is done to a target ----------------------------------------------------
    def erase(self) -> None:
        if (connection := self._connection("Erasing")) is None:
            return
        started = time.monotonic()

        def done(_result) -> None:
            took = time.monotonic() - started
            self.events.good(f"Erased all of the flash of {self.target} in {took:.1f} s.")

        if self._run("Erasing", connection.erase_chip, done):
            self.events.information(f"Erasing all of the flash of {self.target}...")
            self.progress.emit("Erasing", 0.0)

    def program(
        self,
        images: Sequence[Image],
        erase: str = ERASE_SECTORS,
        verify: bool = True,
        reset: bool = True,
    ) -> None:
        """Program these files, then verify and reset if asked to."""
        if (connection := self._connection("Programming")) is None:
            return
        segments: list[Segment] = [s for image in images for s in image.segments]
        if not segments:
            self.events.warning("There is nothing to program: no file is ticked.")
            return
        size = sum(len(s) for s in segments)
        started = time.monotonic()

        def work() -> Verification | None:
            connection.program(segments, erase=erase, progress=self._progress("Programming"))
            result = None
            if verify:
                self._last_progress = -1.0
                result = connection.verify(
                    segments, progress=self._progress("Verifying"), cancelled=self._cancel.is_set
                )
            # Not reset after a verify that failed: what is in the flash is
            # not what was meant to be, and starting it helps nobody.
            if reset and (result is None or result.ok):
                connection.reset()
            return result

        def done(result: Verification | None) -> bool:
            took = time.monotonic() - started
            files = "1 file" if len(images) == 1 else f"{len(images)} files"
            if result is not None and not result.ok:
                self.events.error(
                    f"Programmed {files}, and the target does not hold what was sent. "
                    + verification_text(result)
                )
                return False
            parts = [f"Programmed {files}, {size_text(size)}"]
            if result is not None:
                parts.append("verified")
            if reset:
                parts.append("and reset the target")
            self.events.good(", ".join(parts) + f", in {took:.1f} s.")
            return True

        if self._run("Programming", work, done):
            names = ", ".join(image.name for image in images)
            self.events.information(f"Programming {self.target} with {names}...")

    def verify(self, images: Sequence[Image]) -> None:
        if (connection := self._connection("Verifying")) is None:
            return
        segments: list[Segment] = [s for image in images for s in image.segments]
        if not segments:
            self.events.warning("There is nothing to verify: no file is ticked.")
            return

        def work() -> Verification:
            return connection.verify(
                segments, progress=self._progress("Verifying"), cancelled=self._cancel.is_set
            )

        def done(result: Verification) -> bool:
            (self.events.good if result.ok else self.events.error)(verification_text(result))
            return result.ok

        self._run("Verifying", work, done)

    def read_back(self, address: int, length: int, path: str, trim: bool = False) -> None:
        """Read this much of the target's memory and save it in this file.

        ``trim`` leaves off the erased bytes after the last one that holds
        something, so that the file is the size of what is there.
        """
        if (connection := self._connection("Reading")) is None:
            return
        target = self.target

        def work() -> tuple[str, int] | None:
            data = connection.read_range(
                address, length, self._progress("Reading"), self._cancel.is_set
            )
            if trim:
                data = data.rstrip(b"\xff")
            if not data:
                return None
            try:
                return images.write(path, address, data), len(data)
            except ImageError as exc:
                raise BackendError(f"Saving to {path} failed: {exc}") from exc

        def done(result: tuple[str, int] | None) -> bool:
            where = f"{size_text(length)} at {address:08X} of {target}"
            if result is None:
                self.events.warning(
                    f"Read {where}: all of it is erased, so there was nothing to save."
                )
                return True
            fmt, saved = result
            self.events.good(f"Read {where}, and saved {size_text(saved)} as {fmt} in {path}.")
            return True

        if self._run("Reading", work, done):
            self.events.information(f"Reading {size_text(length)} at {address:08X} of {target}...")

    def reset(self) -> None:
        if (connection := self._connection("Resetting")) is None:
            return
        self._run(
            "Resetting",
            connection.reset,
            lambda _r: self.events.information(f"Reset {self.target}."),
        )

    # --- going away ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Let go of the probe and stop the worker. For when the window closes."""
        if self._shut:
            return  # a window asked to close twice closes once
        self._shut = True
        self._cancel.set()
        connection, self.connection = self.connection, None
        self._worker.stop()
        if connection is not None:
            # After the worker has stopped, so nothing is half way through
            # using it, and here rather than queued, so that it happens
            # before the application has gone.
            try:
                connection.close()
            except BackendError:
                pass
