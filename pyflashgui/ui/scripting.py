# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""``flash``: the probe and the target, for the Python console and its scripts.

Each call does what the button of the same name does -- the same checks,
the same questions, the same lines in the Event Log -- and then waits for it
to finish, so that a script reads in the order it runs::

    flash.connect()
    flash.program("app.hex")
    print(flash.read(0x20000000, 16).hex(" "))

What it waits on is the probe's own worker, which the buttons use too, so a
script and a button never talk to the probe at once. The window is kept
going while it waits: the progress bar moves, Cancel can be pressed, and a
script's own ``print`` arrives as it is printed.

A call that does not do what it was asked raises ``ScriptError``, with the
sentence the Event Log has, so that a script does not carry on as if it had.
``verify`` is the exception: a target that differs from the file is an
answer, and it returns False.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEventLoop, QTimer

from pyflashgui.backends.base import ERASE_NONE, ERASE_SECTORS, Verification
from pyflashgui.core import images
from pyflashgui.core.events import ERROR, WARNING
from pyflashgui.core.images import Image, ImageError
from pyflashgui.core.memory_map import Region, lay_out
from pyflashgui.ui.files_view import Entry

if TYPE_CHECKING:
    from pyflashgui.ui.main_window import MainWindow


class ScriptError(Exception):
    """Something a script asked for was not done. The message says why."""


class ScriptStoppedError(Exception):
    """The script was stopped from the console."""


class Flash:
    """The probe and the target, a call at a time, each waited for."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window
        self._flasher = window.flasher
        self._events = window.events
        self._stopping = False
        #: The event loop being waited in, so that Stop can end it.
        self._loop: QEventLoop | None = None

    def __repr__(self) -> str:
        if self.connected:
            return f"<flash: {self.target} through probe {self.probe}>"
        return "<flash: not connected>"

    # --- what is connected -----------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._flasher.connected

    @property
    def target(self) -> str:
        """The target connected to, or the one chosen in the bar when none is."""
        return self._flasher.target if self.connected else self._bar.chosen_target()

    @property
    def probe(self) -> str:
        return self._flasher.probe if self.connected else self._bar.chosen_probe()

    @property
    def regions(self) -> list[Region]:
        """The target's memory, as far as it is known."""
        return list(self._flasher.regions)

    @property
    def _bar(self):
        return self._window.probe_bar

    @property
    def _files(self):
        return self._window.files_view

    # --- the probe -------------------------------------------------------------------
    def connect(
        self,
        probe: str | None = None,
        target: str | None = None,
        frequency: int | None = None,
        interface: str | None = None,
    ) -> None:
        """Connect, to what the bar has chosen unless told otherwise.

        Nothing is done when that is what is connected already.
        """
        probe = probe or self._bar.chosen_probe()
        target = target or self._bar.chosen_target()
        if not probe or not target:
            raise ScriptError("Not connected: choose a probe and a target, or name them.")
        if self.connected:
            if (probe, target) == (self._flasher.probe, self._flasher.target):
                return
            raise ScriptError(
                f"Not connected: {self._flasher.target} is connected. Disconnect first."
            )
        if frequency is None:
            frequency = self._bar.chosen_frequency()
        if interface is None:
            interface = self._bar.chosen_interface()
        self._do(
            "Connecting",
            lambda: self._flasher.connect_to(probe, target, frequency, interface),
        )

    def disconnect(self) -> None:
        self._ready()
        self._flasher.disconnect()

    # --- what is done to the target --------------------------------------------------
    def read(self, address: int, length: int, show: bool = False) -> bytes:
        """This many bytes of the target's memory. ``show`` also lists them in Files."""
        found: list[bytes] = []
        self._do(
            "Reading",
            lambda: self._flasher.read_memory(address, length, then=found.append),
        )
        data = found[0]
        if show:
            self.show(address, data)
        return data

    def show(self, address: int, data: bytes) -> Entry:
        """List these bytes in Files as a read, to look at, compare or save."""
        return self._files.add_read(address, bytes(data), self.target or "script")

    def write(self, address: int, data: bytes) -> None:
        """Write bytes to RAM or to a peripheral's registers. Never to flash."""
        self._do("Writing", lambda: self._flasher.write_memory(address, bytes(data)))

    def erase(self, address: int | None = None, length: int | None = None) -> None:
        """Erase all of the flash, or ``length`` bytes from ``address``.

        Asks first, as Erase... does, unless that question was ticked away.
        """
        if (address is None) != (length is None):
            raise ScriptError("Not erased: give both an address and a length, or neither.")
        ranges = None if address is None else [(address, length)]
        self._ready()
        if not self._files.may_erase(ranges):
            raise ScriptError("Not erased: the question was answered No.")
        self._do("Erasing", lambda: self._flasher.erase(ranges))

    def program(
        self,
        *files: str | Path | Entry,
        address: int | None = None,
        verify: bool = True,
        erase: bool = True,
        reset: bool = False,
    ) -> None:
        """Program these files, or what is ticked in Files when none are named.

        ``address`` is where a raw binary goes. The files are checked against
        the target's memory first, as the Memory Map checks them. The target
        is left stopped, as Program and verify leaves it, unless ``reset``.
        ``erase=False`` writes to flash erased beforehand, erasing nothing.
        """
        if not erase and not self._flasher.backend.can_skip_erase:
            raise ScriptError(f"{self._flasher.backend.label} cannot program without erasing.")
        loaded = self._images(files, address)
        self._check_layout(loaded)
        self._ready()
        if not self._files.may_program():
            raise ScriptError("Not programmed: the question was answered No.")
        self._do(
            "Programming",
            lambda: self._flasher.program(
                loaded, erase=ERASE_SECTORS if erase else ERASE_NONE, verify=verify, reset=reset
            ),
        )

    def verify(self, *files: str | Path | Entry, address: int | None = None) -> bool:
        """Whether the target holds these files, or what is ticked. Changes nothing."""
        loaded = self._images(files, address)
        found: list[Verification] = []
        self._do("Verifying", lambda: self._flasher.verify(loaded, then=found.append), found)
        return found[0].ok

    def reset(self, halt: bool = False, kind: str = "default") -> None:
        """Restart the target, and leave it stopped at its first instruction if ``halt``.

        ``kind`` is how: "default", or through pyOCD "pin", "system" or "core".
        """
        if kind not in self._flasher.backend.reset_kinds:
            raise ScriptError(
                f"{self._flasher.backend.label} cannot reset that way: "
                + ", ".join(self._flasher.backend.reset_kinds)
                + " are what it can do."
            )
        self._do("Resetting", lambda: self._flasher.reset(halt, kind))

    # --- waiting ---------------------------------------------------------------------
    def wait(self, seconds: float) -> None:
        """A script's sleep: the window goes on working while it waits.

        ``time.sleep`` would stop the window, and Stop with it.
        """
        self._check()
        loop = QEventLoop()
        QTimer.singleShot(max(0, int(seconds * 1000)), loop.quit)
        self._loop = loop
        try:
            loop.exec()
        finally:
            self._loop = None
        self._check()

    def stop(self) -> None:
        """Stop the script at the next call it makes, cancelling what can be."""
        self._stopping = True
        if self._flasher.busy:
            self._flasher.cancel()
        if self._loop is not None and not self._flasher.busy:
            self._loop.quit()

    def started(self) -> None:
        """A script, or a line typed in the console, is about to run."""
        self._stopping = False

    def _check(self) -> None:
        if self._stopping:
            raise ScriptStoppedError("Stopped.")

    def _ready(self) -> None:
        """Wait for whatever a button started to finish, and stop here if asked to."""
        self._check()
        if self._flasher.busy:
            self._wait_until(lambda: not self._flasher.busy)
        self._check()

    def _wait_until(self, done: Callable[[], bool]) -> None:
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(lambda: done() and loop.quit())
        timer.start()
        self._loop = loop
        try:
            if not done():
                loop.exec()
        finally:
            timer.stop()
            self._loop = None

    def _do(self, doing: str, start: Callable[[], bool], answered: list | None = None) -> None:
        """Start one operation, wait for it to finish, and raise if it did not do its job.

        ``answered`` is for an operation whose answer is not success or
        failure: a verify that found differences finished, and said so.
        """
        self._ready()
        said: list[str] = []
        finished: list[bool] = []

        def posted(message: str, level: str) -> None:
            if level in (ERROR, WARNING):
                said.append(message)

        def ended(_name: str, ok: bool) -> None:
            finished.append(ok)

        self._events.posted.connect(posted)
        self._flasher.finished.connect(ended)
        try:
            if not start():
                raise ScriptError(said[-1] if said else f"{doing} was not started.")
            self._wait_until(lambda: bool(finished))
        finally:
            self._events.posted.disconnect(posted)
            self._flasher.finished.disconnect(ended)
        if not finished[0] and not (answered is not None and answered):
            self._check()  # stopped from the console: say that, not what it did to the probe
            raise ScriptError(said[-1] if said else f"{doing} failed.")
        self._check()

    # --- files -----------------------------------------------------------------------
    def _images(self, files: tuple, address: int | None) -> list[Image]:
        if not files:
            ticked = self._files.reread()
            if ticked is None:
                raise ScriptError("A ticked file cannot be read: the Event Log says why.")
            if not ticked:
                raise ScriptError("Nothing is ticked in Files, and no file was named.")
            return ticked
        out = []
        for file in files:
            if isinstance(file, Entry):
                file.read()
                if file.image is None:
                    raise ScriptError(f"{file.name} cannot be read: {file.problem}")
                out.append(file.image)
                continue
            try:
                out.append(images.read(str(file), address))
            except ImageError as exc:
                raise ScriptError(f"{Path(file).name} cannot be read: {exc}") from exc
        return out

    def _check_layout(self, loaded: list[Image]) -> None:
        layout = lay_out(loaded, self._flasher.regions, self._flasher.backend.map_is_complete)
        for problem in layout.problems:
            self._events.post(problem.message, problem.level)
        if not layout.programmable:
            worst = [p.message for p in layout.problems if p.level == ERROR]
            raise ScriptError("Not programmed: " + (worst[0] if worst else "it does not fit."))


def namespace(window: MainWindow, flash: Flash) -> dict[str, Any]:
    """What the console and its scripts see. Keep the names: scripts rely on them."""
    events = window.events

    def log(message: str) -> None:
        """A line in the Event Log."""
        events.information(str(message))

    return {
        "flash": flash,
        "files": window.files_view,
        "window": window,
        "ctx": window.ctx,
        "log": log,
        "wait": flash.wait,
        "ScriptError": ScriptError,
    }
