# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What will be written where: firmware images laid over a target's memory.

Worked out before anything is sent, from the same bytes that will be sent.
A file linked for the wrong part, a binary given the wrong address and two
files that both claim the same sector are all visible here, where finding
them costs nothing, rather than part way through programming a board.

Nothing here touches a probe or Qt. It is handed images and regions and
answers with plain data, which is what makes it testable without either.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pyflashgui.core.events import ERROR, WARNING
from pyflashgui.core.images import Image

FLASH = "flash"
RAM = "ram"
ROM = "rom"
OTHER = "other"
#: Part of the address map every Cortex-M has, which is all a target chosen
#: as no device in particular -- pyOCD's cortex_m -- knows. It says where
#: memory may be, not what is there: not where the flash is, nor how to
#: program it.
GENERIC = "generic"


@dataclass(frozen=True)
class Region:
    """One stretch of a target's memory, and what kind of memory it is."""

    name: str
    start: int
    length: int
    kind: str  # one of FLASH, RAM, ROM, OTHER, GENERIC
    #: What is erased at a time, in bytes. 0 where nothing is: RAM, ROM.
    sector_size: int = 0
    #: What is programmed at a time, in bytes. 0 where it does not apply.
    page_size: int = 0
    #: The region this one is another address for, if it is one. A device may
    #: show the same flash at several addresses and take writes at only one.
    alias_of: str = ""
    #: What a byte of this flash reads as once erased: FF for most devices,
    #: 00 for some -- an XMC4500's does.
    erased: int = 0xFF

    @property
    def end(self) -> int:
        """The address after the last byte."""
        return self.start + self.length

    def __contains__(self, address: int) -> bool:
        return self.start <= address < self.end


@dataclass(frozen=True)
class Piece:
    """Part of one file's data that falls in one region, or in none."""

    source: str  # the file's name
    address: int
    length: int
    region: Region | None

    @property
    def end(self) -> int:
        return self.address + self.length


@dataclass(frozen=True)
class Usage:
    """How much of one flash region the files take up."""

    region: Region
    used: int  # bytes the files write
    sectors: int  # sectors those bytes touch, each of which is erased whole

    @property
    def erased(self) -> int:
        """Bytes erased to make room: every touched sector, all of it."""
        return self.sectors * self.region.sector_size

    @property
    def fraction(self) -> float:
        return self.used / self.region.length if self.region.length else 0.0


@dataclass(frozen=True)
class Problem:
    """Something about the layout that needs looking at before programming."""

    level: str  # WARNING or ERROR, as the Event Log has them
    message: str


@dataclass
class Layout:
    """Every piece of every file, where it lands, and what is wrong with that."""

    pieces: list[Piece] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)
    #: False when the target's memory is not known, so nothing could be
    #: checked against it: the pieces are listed and none is called wrong.
    checked: bool = True

    @property
    def programmable(self) -> bool:
        """Whether programming can go ahead: nothing here is an error."""
        return not any(p.level == ERROR for p in self.problems)


def region_at(regions: Sequence[Region], address: int) -> Region | None:
    for region in regions:
        if address in region:
            return region
    return None


def _split(source: str, address: int, length: int, regions: Sequence[Region]) -> list[Piece]:
    """One run of bytes, cut wherever it crosses from one region to another."""
    pieces = []
    end = address + length
    while address < end:
        region = region_at(regions, address)
        if region is not None:
            stop = min(end, region.end)
        else:
            # Up to the next region that starts inside the run, or all of it.
            starts = [r.start for r in regions if address < r.start < end]
            stop = min(starts, default=end)
        pieces.append(Piece(source, address, stop - address, region))
        address = stop
    return pieces


def _span(address: int, end: int) -> str:
    return f"{address:08X} to {end - 1:08X}"


def _bytes(count: int) -> str:
    return "1 byte" if count == 1 else f"{count} bytes"


def _overlaps(pieces: Iterable[Piece]) -> list[Problem]:
    """Where two runs of bytes claim the same addresses.

    An error whichever files they are from: the second to be written wins, and
    which is second is not something anybody chose.
    """
    problems = []
    ordered = sorted(pieces, key=lambda p: (p.address, p.end))
    reach: Piece | None = None  # the piece seen so far that ends furthest on
    for piece in ordered:
        if reach is not None and piece.address < reach.end:
            end = min(piece.end, reach.end)
            who = (
                f"{reach.source} and {piece.source} both write"
                if reach.source != piece.source
                else f"{piece.source} writes twice to"
            )
            problems.append(Problem(ERROR, f"{who} {_span(piece.address, end)}."))
        if reach is None or piece.end > reach.end:
            reach = piece
    return problems


def _placement(piece: Piece, complete: bool = True) -> Problem | None:
    """What is wrong with where one piece lands, if anything is."""
    what = f"{piece.source}: {_bytes(piece.length)} at {_span(piece.address, piece.end)}"
    region = piece.region
    if region is None:
        if not complete:
            return Problem(
                WARNING,
                f"{what} are outside the memory listed for this target, which may not "
                "be all of it.",
            )
        return Problem(ERROR, f"{what} are outside the target's memory.")
    if region.alias_of:
        return Problem(
            ERROR,
            f"{what} are in {region.name}, which is another address for "
            f"{region.alias_of} and cannot be programmed through.",
        )
    if region.kind == GENERIC:
        return None  # said once for every file, by _generic
    if region.kind == RAM:
        # Not refused: loading a program into RAM to run it is a real thing
        # to do. But it is not what a file meant for flash should be doing.
        return Problem(
            WARNING,
            f"{what} go to RAM ({region.name}), not flash: written there, they stay on "
            "the device only until it is next reset.",
        )
    if region.kind != FLASH:
        return Problem(ERROR, f"{what} are in {region.name}, which cannot be written.")
    return None


def _generic(pieces: Iterable[Piece]) -> Problem | None:
    """Files laid over no more than the Cortex-M address map, said once.

    An error, not the warning RAM would have: the map calls 0 to 1FFFFFFF
    RAM because it may be, and on a real device the flash is there. What the
    target does not know is how to program it.
    """
    names = list(dict.fromkeys(p.source for p in pieces if p.region and p.region.kind == GENERIC))
    if not names:
        return None
    return Problem(
        ERROR,
        f"{', '.join(names)}: the target chosen is no device in particular, and knows only "
        "the address map every Cortex-M has, not where this device's flash is or how to "
        "program it. It can read and compare; to program, choose the device itself, "
        "from its pack if it is not built in (Tools > pyOCD device packs).",
    )


def _usage(pieces: Iterable[Piece], regions: Sequence[Region]) -> list[Usage]:
    """What each flash region holds, for the ones anything is written to."""
    out = []
    for region in regions:
        if region.kind != FLASH or region.alias_of:
            continue
        mine = [p for p in pieces if p.region is region]
        if not mine:
            continue
        sectors: set[int] = set()
        if region.sector_size:
            for piece in mine:
                first = (piece.address - region.start) // region.sector_size
                last = (piece.end - 1 - region.start) // region.sector_size
                sectors.update(range(first, last + 1))
        out.append(Usage(region, used=sum(p.length for p in mine), sectors=len(sectors)))
    return out


def lay_out(images: Iterable[Image], regions: Sequence[Region], complete: bool = True) -> Layout:
    """Where every byte of these files would go on a target with this memory.

    ``complete`` says whether the regions are every address the target can
    be written at. Where they may not be, bytes outside them are a warning
    and not an error: refusing a file that the target would have taken is
    worse than passing on one that it will refuse for itself.

    With no regions -- a target whose memory is not known until it is
    connected to -- the pieces are still listed and overlaps still found, and
    ``checked`` says that nothing was compared with the target.
    """
    layout = Layout(checked=bool(regions))
    for image in images:
        for segment in image.segments:
            layout.pieces += _split(image.name, segment.address, len(segment), regions)
    layout.problems += _overlaps(layout.pieces)
    if layout.checked:
        found = (_placement(piece, complete) for piece in layout.pieces)
        layout.problems += [p for p in found if p is not None]
        if generic := _generic(layout.pieces):
            layout.problems.append(generic)
        layout.usage = _usage(layout.pieces, regions)
    return layout
