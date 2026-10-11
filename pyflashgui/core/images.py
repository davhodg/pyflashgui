# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Firmware images: ELF, Intel HEX, Motorola S-record and raw binary.

Reading and writing is bincopy's job. What is here is the part bincopy cannot decide:
which format a file is, what its address is, and what to do when it does not
have one.

Every format is read the same way and comes out as the same thing -- runs of
bytes, each at an address -- so that the memory map and whatever does the
programming are shown exactly the bytes that were read, rather than each
reading the file again in its own way and the two disagreeing.

An ELF, a hex or an S-record file carries the address of every byte in it. A
raw binary does not -- it is bytes and nothing else -- so the address has to
be supplied before it can be put anywhere, and an image loaded without one
says so rather than guessing at zero.

**An ELF is read at its load addresses.** Initialised data is linked to run
from RAM and stored in flash, and the two addresses are both in the file. The
load address is where the bytes have to be programmed; the other is where
start-up code copies them to, which is no business of a programmer's.

Gaps are left as they are found. Padding the holes in a file would mean
writing bytes it never contained, over whatever the target had there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# bincopy is needed only when somebody picks a firmware file, so it is
# imported in the function that reads one.

ELF = "ELF"
IHEX = "Intel HEX"
SREC = "Motorola S-record"
BINARY = "raw binary"

#: Suffixes that mean "this file has no addresses in it".
BINARY_SUFFIXES = {".bin", ".raw", ".img", ".rom", ".dat"}

#: For the file dialogs. One "any of them" entry first, because guessing the
#: format from the contents is what the reader does anyway.
READ_FILTER = (
    "Firmware images (*.elf *.axf *.out *.hex *.ihex *.ihx *.s19 *.s28 *.s37 *.srec *.mot "
    "*.bin *.raw *.img);;"
    "ELF (*.elf *.axf *.out);;"
    "Intel HEX (*.hex *.ihex *.ihx);;"
    "Motorola S-record (*.s19 *.s28 *.s37 *.srec *.mot);;"
    "Raw binary (*.bin *.raw *.img);;"
    "All files (*)"
)

#: S-record address widths, by the suffix that names them. S19 is 16-bit
#: addresses, S28 24-bit, S37 32-bit; the suffix is the usual way of saying so.
SREC_SUFFIXES = {".s19": 16, ".s28": 24, ".s37": 32, ".srec": 32, ".mot": 32, ".sre": 32}
IHEX_SUFFIXES = {".hex", ".ihex", ".ihx", ".i32", ".a90"}

#: For saving what was read back. Raw binary first: it is what was read,
#: with nothing added.
WRITE_FILTER = (
    "Raw binary (*.bin);;Intel HEX (*.hex);;Motorola S-record (*.s19 *.s28 *.s37);;All files (*)"
)

#: How an ELF file starts, whatever it is called.
_ELF_MAGIC = b"\x7fELF"


class ImageError(Exception):
    """The file could not be read, or could be read but not placed."""


@dataclass(frozen=True)
class Segment:
    """One run of contiguous bytes at a known address."""

    address: int
    data: bytes

    def __len__(self) -> int:
        return len(self.data)

    @property
    def end(self) -> int:
        """The address after the last byte."""
        return self.address + len(self.data)


@dataclass(frozen=True)
class Image:
    """What a firmware file turned out to contain."""

    path: str
    format: str  # one of ELF, IHEX, SREC, BINARY
    segments: tuple[Segment, ...]
    #: Lines of an Intel HEX file that were not records -- comments, a title
    #: -- and so were passed over. Said in the summary, so it is never silent.
    ignored: int = 0
    #: Where execution starts, for a file that says: an ELF always does, and
    #: a hex or S-record file may. None for one that does not.
    entry: int | None = None

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def size(self) -> int:
        return sum(len(s) for s in self.segments)

    @property
    def address(self) -> int:
        return self.segments[0].address if self.segments else 0

    def summary(self) -> str:
        """One line: what was read, how much of it, and where it goes."""
        if not self.segments:
            return f"{self.name}: {self.format}, empty"
        where = ", ".join(f"{s.address:08X}+{len(s)}" for s in self.segments[:4])
        if len(self.segments) > 4:
            where += f", and {len(self.segments) - 4} more"
        segments = "1 segment" if len(self.segments) == 1 else f"{len(self.segments)} segments"
        line = f"{self.name}: {self.format}, {self.size} bytes, {segments} [{where}]"
        if self.ignored:
            lines = "1 line" if self.ignored == 1 else f"{self.ignored} lines"
            line += f"; {lines} not starting with ':' ignored"
        return line


def looks_binary(path: str) -> bool:
    """Whether choosing this file will need an address typed in.

    Answered from the name, because a pane has to enable or disable the
    address box the moment a file is picked; reading settles it properly.
    """
    return Path(path).suffix.lower() in BINARY_SUFFIXES


#: An Intel HEX record: a colon, then hex digits -- at least a length, an
#: address, a type and a checksum.
_IHEX_RECORD = re.compile(rb"^:[0-9A-Fa-f]{10,}$")


def _sniff(raw: bytes) -> str | None:
    """Which format carries its own addresses here, or None for none of them.

    From the contents, not the name: a build that calls its ELF ``firmware``
    or its hex file ``image.txt`` has still made an ELF and a hex file.
    """
    if raw.startswith(_ELF_MAGIC):
        return ELF
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith(b":"):
            return IHEX
        if text[:1] in (b"S", b"s") and text[1:2].isdigit():
            return SREC
        break
    # Intel HEX that opens with a comment or a title. Every record starts with
    # a colon, so anything else in a text file of records is not data.
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError:
        return None
    if any(_IHEX_RECORD.match(line.strip().encode()) for line in lines):
        return IHEX
    return None


def _ihex_records(text: str) -> tuple[str, int]:
    """The records of an Intel HEX file, and how many other lines there were."""
    records, ignored = [], 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(":"):
            records.append(stripped)
        elif stripped:
            ignored += 1
    return "\n".join(records) + "\n", ignored


def read(path: str, address: int | None = None) -> Image:
    """Read a firmware file, whatever format it is in.

    `address` is where a raw binary starts. It is required for one, ignored
    for a file that carries its own addresses -- there the file is right and a
    typed-in number would only be a way to get it wrong.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ImageError(str(exc)) from exc
    if not raw:
        raise ImageError("the file is empty")

    import bincopy

    binfile = bincopy.BinFile()
    fmt = _sniff(raw)
    ignored = 0
    if fmt == ELF:
        try:
            binfile.add_elf(raw)
        except Exception as exc:
            # Not bincopy's own error alone: a damaged ELF fails inside the
            # ELF reader, in whichever way the damage takes it.
            raise ImageError(f"not readable as {fmt}: {exc}") from exc
        if not binfile.segments:
            raise ImageError("this ELF has nothing in it to program: no loadable section")
    elif fmt is not None:
        try:
            text = raw.decode("ascii", "strict")
            if fmt == IHEX:
                text, ignored = _ihex_records(text)
                binfile.add_ihex(text)
            else:
                binfile.add_srec(text)
        except (UnicodeDecodeError, bincopy.Error, ValueError) as exc:
            raise ImageError(f"not readable as {fmt}: {exc}") from exc
    else:
        if address is None:
            raise ImageError(
                "this file is raw binary -- it carries no addresses, so the "
                "start address has to be supplied"
            )
        fmt = BINARY
        binfile.add_binary(raw, address=address)

    segments = tuple(Segment(s.address, bytes(s.data)) for s in binfile.segments)
    return Image(
        path=path,
        format=fmt,
        segments=segments,
        ignored=ignored,
        entry=binfile.execution_start_address,
    )


def _srec_width(suffix: str, address: int, size: int) -> int:
    """How wide the addresses of an S-record file have to be.

    What the suffix asks for, or wider where the addresses will not fit:
    flash at 08000000 saved as .s19 is given 32-bit addresses rather
    than refused, since a file that holds the data is what was wanted.
    """
    top = address + size
    needed = 16 if top <= 0x1_0000 else 24 if top <= 0x100_0000 else 32
    return max(SREC_SUFFIXES.get(suffix, needed), needed)


def write(path: str, address: int, data: bytes) -> str:
    """Write bytes read back from a target, in the format the name asks for.

    Exactly what was read, at the address it was read from: nothing padded
    and nothing filled in. Returns the format used, for the log.
    """
    import bincopy

    binfile = bincopy.BinFile()
    binfile.add_binary(data, address=address)
    suffix = Path(path).suffix.lower()
    try:
        if suffix in IHEX_SUFFIXES:
            fmt, text = IHEX, binfile.as_ihex()
        elif suffix in SREC_SUFFIXES:
            width = _srec_width(suffix, address, len(data))
            fmt, text = SREC, binfile.as_srec(address_length_bits=width)
        else:
            Path(path).write_bytes(data)
            return BINARY
        Path(path).write_text(text, encoding="ascii")
    except (OSError, bincopy.Error, ValueError) as exc:
        raise ImageError(str(exc)) from exc
    return fmt
