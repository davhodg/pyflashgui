# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What was read from a target against what a file says should be there.

The same question Verify asks, the other way about: Verify reads what the
files cover and says whether it matches, and this takes what has already been
read -- any stretch of memory, from any time -- and says where a file agrees
with it and where it does not.

A file and a read rarely cover the same addresses. Only where they overlap is
there anything to compare, and what each has that the other does not is
counted and said rather than called a difference: flash the file does not
mention is not flash the file says is wrong.

Nothing here touches a probe or Qt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pyflashgui.core.images import Image, Segment

SAME, DIFFERENT = 0, 1


@dataclass(frozen=True)
class Comparison:
    """Where a file and a read agree, byte by byte over the read."""

    #: The file's name, for saying what was compared with.
    name: str
    #: Where the read starts.
    address: int
    #: A byte for each byte read: DIFFERENT where the file has another value
    #: there, SAME where it has the same or says nothing.
    differs: bytes
    #: A byte for each byte read: 1 where the file has a value for it.
    covered: bytes
    #: The file's value for each byte read, where it has one.
    file: bytes
    #: Bytes the file has at addresses that were not read.
    outside: int

    @property
    def compared(self) -> int:
        """Bytes that both have, which is all that could be compared."""
        return self.covered.count(1)

    @property
    def different(self) -> int:
        return self.differs.count(DIFFERENT)

    @property
    def unmentioned(self) -> int:
        """Bytes read that the file says nothing about."""
        return len(self.covered) - self.compared

    @property
    def first(self) -> int | None:
        """The offset of the first byte that differs, or None when none does."""
        at = self.differs.find(DIFFERENT)
        return at if at >= 0 else None

    def run_from(self, offset: int) -> int:
        """How many bytes in a row differ, starting at this one."""
        end = self.differs.find(SAME, offset)
        return (len(self.differs) if end < 0 else end) - offset

    def next_run(self, after: int | None) -> int | None:
        """Where the next stretch of differing bytes starts, going round at the end.

        ``after`` is where the last one shown starts, or None for the first
        of all. None back when nothing differs.
        """
        if self.first is None:
            return None
        if after is None:
            return self.first
        end = self.differs.find(SAME, after)
        at = -1 if end < 0 else self.differs.find(DIFFERENT, end)
        return at if at >= 0 else self.first

    def previous_run(self, before: int | None) -> int | None:
        """Where the stretch of differing bytes before this one starts, going round."""
        if self.first is None:
            return None
        last = self.differs.rfind(DIFFERENT, 0, before) if before else -1
        if last < 0:
            last = self.differs.rfind(DIFFERENT)
        # Back from its last byte to its first: the byte after the one
        # before it that does not differ.
        return self.differs.rfind(SAME, 0, last) + 1


#: Any byte but zero becomes DIFFERENT: what two bytes exclusive-or to is
#: zero only where they are the same.
_ANY_BIT = bytes([SAME]) + bytes([DIFFERENT]) * 255


def _unlike(one: bytes, other: bytes) -> bytes:
    """A byte for each pair: DIFFERENT where the two are not the same.

    As two whole numbers, exclusive-ored: a megabyte compared a byte at a
    time in Python is a second of a window that does not answer.
    """
    mixed = int.from_bytes(one, "big") ^ int.from_bytes(other, "big")
    return mixed.to_bytes(len(one), "big").translate(_ANY_BIT)


def compare(address: int, data: bytes, image: Image) -> Comparison:
    """Lay a file over what was read from ``address``, and mark where they differ."""
    file = bytearray(len(data))
    covered = bytearray(len(data))
    differs = bytearray(len(data))
    outside = 0
    end = address + len(data)
    for segment in image.segments:
        start = max(segment.address, address)
        stop = min(segment.end, end)
        overlap = max(0, stop - start)
        outside += len(segment) - overlap
        if overlap:
            at, within = start - address, start - segment.address
            wanted = segment.data[within : within + overlap]
            file[at : at + overlap] = wanted
            covered[at : at + overlap] = b"\x01" * overlap
            differs[at : at + overlap] = _unlike(wanted, data[at : at + overlap])
    return Comparison(
        name=image.name,
        address=address,
        differs=bytes(differs),
        covered=bytes(covered),
        file=bytes(file),
        outside=outside,
    )


def compare_all(segments: Sequence[Segment], image: Image) -> Comparison:
    """Lay a file over several runs of memory, one after another.

    For what is shown in pieces, as a file with gaps in it is. The marks
    are for the pieces end to end, in the order given, and ``address`` is
    where the first starts: where a later byte is, is for whoever holds the
    pieces to say.
    """
    made = [compare(segment.address, segment.data, image) for segment in segments]
    covered = b"".join(one.covered for one in made)
    return Comparison(
        name=image.name,
        address=segments[0].address if segments else 0,
        differs=b"".join(one.differs for one in made),
        covered=covered,
        file=b"".join(one.file for one in made),
        outside=image.size - covered.count(1),
    )
