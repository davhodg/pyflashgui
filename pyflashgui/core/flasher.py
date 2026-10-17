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
    ERASE_NONE,
    ERASE_SECTORS,
    RESET_CORE,
    RESET_DEFAULT,
    RESET_PIN,
    RESET_SYSTEM,
    Backend,
    BackendError,
    CancelledError,
    Connection,
    Verification,
)
from pyflashgui.core.events import EventLog
from pyflashgui.core.images import Image, Segment
from pyflashgui.core.memory_map import FLASH, Region
from pyflashgui.core.worker import Worker

#: How each way of resetting is said in the Event Log: "Reset X by its reset pin."
RESET_SAID = {
    RESET_SYSTEM: "by software",
    RESET_PIN: "by its reset pin",
    RESET_CORE: "by restarting its processor only",
}
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
    #: Looking for probes has started, or has finished however it went.
    #: It can take a second or two, and is not being busy: nothing else
    #: waits for it.
    looking_for_probes = Signal(bool)
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
    #: Memory was read from a target: where it starts, the bytes, and the
    #: target they came from.
    memory_read = Signal(int, bytes, str)

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

    def _progress(self, label: str) -> Callable[..., None]:
        """A progress callback for the worker thread, saying this is what is done.

        Emitting a signal from another thread is the one thing here that is
        safe to do from it: Qt queues it for the GUI thread. A backend that
        does the work in stages says so as it goes from one to the next.
        """

        def report(fraction: float, doing: str | None = None) -> None:
            nonlocal label
            if doing is not None and doing != label:
                label, self._last_progress = doing, -1.0
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

        def work() -> tuple[list, str]:
            # Caught here rather than by _run, so that the end of looking is
            # said even when the looking failed.
            try:
                return backend.probes(), ""
            except BackendError as exc:
                return [], str(exc)

        def done(result: tuple[list, str]) -> None:
            probes, error = result
            if error:
                self.events.warning(error)
            self.probes_changed.emit(probes)
            self.looking_for_probes.emit(False)

        self.looking_for_probes.emit(True)
        if not self._run("Looking for probes", work, done, quiet=True):
            self.looking_for_probes.emit(False)

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
        stop: bool = True,
    ) -> bool:
        backend = self.backend

        def work() -> tuple[Connection, list[Region]]:
            connection = backend.connect(probe, target, frequency, interface, stop)
            try:
                return connection, connection.regions()
            except Exception:
                connection.close()
                raise

        def done(result: tuple[Connection, list[Region]]) -> None:
            self.connection, self.regions = result
            self.probe, self.target = probe, target
            self._regions_for = target
            at = f" at {self.connection.speed}" if self.connection.speed else ""
            running = "" if stop or not backend.can_attach else ", leaving it running"
            self.events.good(f"Connected to {target} through probe {probe}{at}{running}.")
            for note in self.connection.notes:
                self.events.warning(note)
            self.connection_changed.emit(True)
            self.regions_changed.emit()

        if not self._run(f"Connecting to {target}", work, done):
            return False
        self.events.information(f"Connecting to {target} through probe {probe}...")
        return True

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
    def erase(self, ranges: Sequence[tuple[int, int]] | None = None) -> bool:
        """Erase all of the target's flash, or these stretches of it.

        Each of ``ranges`` is an address and a length. Like every operation
        here, returns whether it was started, having said why when it was not.
        """
        if (connection := self._connection("Erasing")) is None:
            return False
        target = self.target
        started = time.monotonic()
        if ranges is None:
            what = f"all of the flash of {target}"
            work = connection.erase_chip
        else:
            asked = list(ranges)
            what = ", ".join(f"{a:08X} to {a + n - 1:08X}" for a, n in asked) + f" of {target}"

            def work() -> None:
                connection.erase_ranges(asked)

        def done(_result) -> None:
            took = time.monotonic() - started
            self.events.good(f"Erased {what} in {took:.1f} s.")

        if not self._run("Erasing", work, done):
            return False
        self.events.information(f"Erasing {what}...")
        self.progress.emit("Erasing", 0.0)
        return True

    def program(
        self,
        images: Sequence[Image],
        erase: str = ERASE_SECTORS,
        verify: bool = True,
        reset: bool = True,
    ) -> bool:
        """Program these files, then verify and reset if asked to."""
        if (connection := self._connection("Programming")) is None:
            return False
        if erase == ERASE_NONE and not self.backend.can_skip_erase:
            self.events.warning(f"{self.backend.label} cannot program without erasing.")
            return False
        segments: list[Segment] = [s for image in images for s in image.segments]
        if not segments:
            self.events.warning("There is nothing to program: no file is ticked.")
            return False
        size = sum(len(s) for s in segments)
        started = time.monotonic()

        def work() -> tuple[Verification | None, str | None]:
            note = connection.program(segments, erase=erase, progress=self._progress("Programming"))
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
            return result, note

        def done(made: tuple[Verification | None, str | None]) -> bool:
            result, note = made
            took = time.monotonic() - started
            if note:
                self.events.information(note)
            files = "1 file" if len(images) == 1 else f"{len(images)} files"
            if result is not None and not result.ok:
                self.events.error(
                    f"Programmed {files}, and the target does not hold what was sent. "
                    + verification_text(result)
                )
                return False
            parts = [f"Programmed {files}, {size_text(size)}"]
            if erase == ERASE_NONE:
                parts.append("without erasing")
            if result is not None:
                parts.append("verified")
            if reset:
                parts.append("and reset the target")
            self.events.good(", ".join(parts) + f", in {took:.1f} s.")
            return True

        if not self._run("Programming", work, done):
            return False
        names = ", ".join(image.name for image in images)
        unerased = ", without erasing" if erase == ERASE_NONE else ""
        self.events.information(f"Programming {self.target} with {names}{unerased}...")
        return True

    def verify(
        self,
        images: Sequence[Image],
        then: Callable[[Verification], None] | None = None,
    ) -> bool:
        """Compare the target with these files. ``then`` is handed what was found."""
        if (connection := self._connection("Verifying")) is None:
            return False
        segments: list[Segment] = [s for image in images for s in image.segments]
        if not segments:
            self.events.warning("There is nothing to verify: no file is ticked.")
            return False

        def work() -> Verification:
            return connection.verify(
                segments, progress=self._progress("Verifying"), cancelled=self._cancel.is_set
            )

        def done(result: Verification) -> bool:
            (self.events.good if result.ok else self.events.error)(verification_text(result))
            if then is not None:
                then(result)
            return result.ok

        return self._run("Verifying", work, done)

    def read_memory(
        self,
        address: int,
        length: int,
        skip_setup: bool = False,
        then: Callable[[bytes], None] | None = None,
    ) -> bool:
        """Read this much of the target's memory, and say so with ``memory_read``.

        Into memory and not into a file: most reads are to look at what is
        there, and whoever shows it can save it once it has been looked at.
        Handed to ``then`` instead, where that is given: a script reading
        the same word a hundred times wants the bytes, not a hundred reads
        in the Files list.
        """
        if (connection := self._connection("Reading")) is None:
            return False
        target = self.target

        def work() -> bytes:
            return connection.read_range(
                address, length, self._progress("Reading"), self._cancel.is_set, skip_setup
            )

        def done(data: bytes) -> None:
            if then is not None:
                then(data)
                return
            self.events.good(f"Read {size_text(len(data))} at {address:08X} of {target}.")
            self.memory_read.emit(address, data, target)

        if not self._run("Reading", work, done):
            return False
        if then is None:
            self.events.information(f"Reading {size_text(length)} at {address:08X} of {target}...")
        return True

    def write_memory(self, address: int, data: bytes) -> bool:
        """Write these bytes to RAM, or to a peripheral's registers.

        Never to flash, which is erased and programmed: written to as if it
        were RAM it either refuses or does something nobody meant.
        """
        if (connection := self._connection("Writing")) is None:
            return False
        data = bytes(data)
        if not data:
            self.events.warning("There is nothing to write: no bytes were given.")
            return False
        end = address + len(data)
        for region in self.regions:
            if region.kind == FLASH and region.start < end and address < region.end:
                span = f"{address:08X}" if len(data) == 1 else f"{address:08X} to {end - 1:08X}"
                self.events.warning(
                    f"Not written: {span} is flash ({region.name}), and flash is programmed "
                    "rather than written to."
                )
                return False
        target = self.target

        def work() -> None:
            connection.write(address, data)

        def done(_result) -> None:
            self.events.information(f"Wrote {size_text(len(data))} at {address:08X} of {target}.")

        return self._run("Writing", work, done)

    def reset(self, halt: bool = False, kind: str = RESET_DEFAULT) -> bool:
        """Restart the target, and leave it stopped at its first instruction if ``halt``.

        ``kind`` is how, one of the backend's ``reset_kinds``.
        """
        if (connection := self._connection("Resetting")) is None:
            return False
        if kind not in self.backend.reset_kinds:
            self.events.warning(f"{self.backend.label} cannot reset {RESET_SAID.get(kind, kind)}.")
            return False
        how = f" {RESET_SAID[kind]}" if kind != RESET_DEFAULT else ""
        said = f"Reset {self.target}{how}" + (", and stopped it." if halt else ".")
        return self._run(
            "Resetting",
            lambda: connection.reset(halt, kind),
            lambda note: self._reset_done(said, note),
        )

    def _reset_done(self, said: str, note: str | None) -> None:
        self.events.information(said)
        if note:
            self.events.information(note)

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
