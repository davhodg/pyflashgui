# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What pyflashgui asks of whatever talks to a probe.

Two objects. A ``Backend`` knows what is plugged in and which targets it can
handle, and none of that needs anything connected. A ``Connection`` is one
probe attached to one target, and is what erases, programs and reads.

The rest of pyflashgui is written against these and never against a
flashing library, for two reasons. A second library can be added behind the
same interface without a pane noticing; and the simulated backend stands in
for a probe in the tests, and on a desk with no hardware on it.

**Every call blocks**, some of them for as long as programming takes. They
are meant to be run on a worker thread, one at a time for a given probe:
nothing here is safe to call from two threads at once, because a probe is
not.

Nothing here imports Qt or a flashing library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import Region

#: Called with how far along something is, from 0.0 to 1.0.
Progress = Callable[[float], None]
#: Asked between steps whether to stop. True means somebody pressed Cancel.
Cancelled = Callable[[], bool]

#: Erase only the sectors about to be written, leaving the rest of the flash.
ERASE_SECTORS = "sectors"
#: Erase all of the flash first, so nothing of what was there is left.
ERASE_CHIP = "chip"

#: What verifying reads at a time. Small enough that progress moves and a
#: cancel is noticed; large enough that the probe is not asked a thousand
#: times for one sector.
VERIFY_CHUNK = 4096
#: What reading back asks for at a time, for the same two reasons.
READ_CHUNK = 0x4000


class BackendError(Exception):
    """Something went wrong that the user can be told about in its own words.

    Raised with a whole sentence, because the message is what is shown: a
    library's own exception is caught where it is raised and said again here
    in terms of what was being attempted.
    """


class CancelledError(BackendError):
    """Stopped because it was asked to, and not because anything failed."""


@dataclass(frozen=True)
class ProbeInfo:
    """One debug probe that is plugged in."""

    #: What tells this probe from another of the same kind: its serial number.
    unique_id: str
    description: str
    vendor: str = ""
    product: str = ""


@dataclass(frozen=True)
class TargetInfo:
    """One kind of device a backend knows how to program."""

    #: What the backend calls it, and what ``connect`` is given.
    name: str
    vendor: str = ""
    #: Where the backend's knowledge of it comes from: "built in", or the
    #: pack it was installed with.
    source: str = ""
    #: The processor in it, where the backend knows: "Cortex-M7".
    core: str = ""


@dataclass(frozen=True)
class Verification:
    """What comparing a target's memory with the files found."""

    checked: int  # bytes compared
    different: int  # bytes that were not what the file has
    #: The first byte that differed -- its address, what the file has there
    #: and what the target has -- or None when nothing did.
    first: tuple[int, int, int] | None = None

    @property
    def ok(self) -> bool:
        return self.different == 0


def _nothing(_fraction: float) -> None:
    """Progress nobody is listening to."""


def _never() -> bool:
    return False


class Connection(ABC):
    """One probe, attached to one target. Closed when finished with.

    Usable in a ``with`` statement, which closes it however the block ends:
    a probe left attached is one nothing else can use.
    """

    @abstractmethod
    def regions(self) -> list[Region]:
        """The target's memory, as it turned out to be once connected."""

    @abstractmethod
    def erase_chip(self) -> None:
        """Erase all of the target's flash."""

    @abstractmethod
    def erase_ranges(self, ranges: Sequence[tuple[int, int]]) -> None:
        """Erase these stretches of flash, each an address and a length.

        Flash is erased a sector at a time, so every sector that any of
        a range falls in is erased whole.
        """

    @abstractmethod
    def program(
        self,
        segments: Sequence[Segment],
        erase: str = ERASE_SECTORS,
        progress: Progress = _nothing,
    ) -> None:
        """Erase what has to be erased and write these bytes.

        Not cancellable. Stopping half way through leaves a target that is
        neither what it was nor what it was going to be, which is worse than
        either; a board can always be programmed again afterwards.
        """

    @abstractmethod
    def read(self, address: int, length: int) -> bytes:
        """This many bytes of the target's memory, from this address."""

    @abstractmethod
    def reset(self, halt: bool = False) -> None:
        """Restart the target, and leave it running unless ``halt``."""

    @abstractmethod
    def close(self) -> None:
        """Let go of the probe. Safe to call twice."""

    def read_range(
        self,
        address: int,
        length: int,
        progress: Progress = _nothing,
        cancelled: Cancelled = _never,
        skip_setup: bool = False,
    ) -> bytes:
        """A long run of the target's memory, a piece at a time.

        ``skip_setup`` asks a backend that sets a device up on connecting
        to it -- which on some parts writes to its RAM -- to leave that
        out for this read. It means something only where the backend's
        ``can_skip_setup`` says so, and is passed over elsewhere.

        In pieces so that there is progress to report and a cancel is
        noticed: a megabyte asked for in one go is a window that says
        nothing for as long as it takes.
        """
        out = bytearray()
        while len(out) < length:
            if cancelled():
                raise CancelledError("Reading was cancelled.")
            out += self.read(address + len(out), min(READ_CHUNK, length - len(out)))
            progress(len(out) / length)
        return bytes(out)

    def verify(
        self,
        segments: Sequence[Segment],
        progress: Progress = _nothing,
        cancelled: Cancelled = _never,
    ) -> Verification:
        """Read back what these bytes should have become, and compare.

        Read through ``read`` rather than left to a library's own check, so
        that it means the same thing with every backend: the bytes that are
        in the target now are the bytes that are in the file.
        """
        total = sum(len(s) for s in segments)
        checked = different = 0
        first: tuple[int, int, int] | None = None
        for segment in segments:
            for offset in range(0, len(segment), VERIFY_CHUNK):
                if cancelled():
                    raise CancelledError("Verifying was cancelled.")
                wanted = segment.data[offset : offset + VERIFY_CHUNK]
                found = self.read(segment.address + offset, len(wanted))
                if found != wanted:
                    for index, (want, have) in enumerate(zip(wanted, found, strict=True)):
                        if want != have:
                            different += 1
                            if first is None:
                                first = (segment.address + offset + index, want, have)
                checked += len(wanted)
                progress(checked / total)
        return Verification(checked=checked, different=different, first=first)

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class Backend(ABC):
    """One way of reaching probes and targets."""

    #: What the backend is called in settings, which must not change.
    name: str = ""
    #: What it is called on screen.
    label: str = ""
    #: The debug interfaces that can be asked for, the first being the
    #: one used when none is. Empty where the backend chooses for itself.
    interfaces: tuple[str, ...] = ()
    #: Whether ``regions`` is every address the target can be written at.
    #: Where it is not, a file outside them is worth a warning and is
    #: not refused: the backend may know of memory that it does not list.
    map_is_complete: bool = True
    #: Whether a read can be made without the backend first setting the
    #: device up in its own way. See ``Connection.read_range``.
    can_skip_setup: bool = False

    @abstractmethod
    def probes(self) -> list[ProbeInfo]:
        """The probes plugged in now. Empty when there are none: never waits."""

    @abstractmethod
    def targets(self) -> list[TargetInfo]:
        """Every target this backend can be asked for, by name."""

    @abstractmethod
    def regions(self, target: str) -> list[Region]:
        """A target's memory as far as is known without connecting to one.

        Empty when it is not known until then, which is not an error: the
        memory map says it could not check, and ``Connection.regions`` has
        the answer once there is a connection.
        """

    @abstractmethod
    def connect(
        self,
        probe: str,
        target: str,
        frequency: int | None = None,
        interface: str | None = None,
    ) -> Connection:
        """Attach the probe with this unique id to a target of this name.

        ``frequency`` is the debug clock in hertz, or None for the probe's
        own choice. ``interface`` is one of ``interfaces``, or None for
        the first of them.
        """
