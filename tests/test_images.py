# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Firmware files: every format read into the same runs of bytes at addresses."""

import struct

import bincopy
import pytest

from pyflashgui.core import images
from pyflashgui.core.images import ImageError

CODE = bytes(range(256))
DATA = b"\xde\xad\xbe\xef" * 8


def at(image, address: int, length: int) -> bytes:
    """The bytes an image has at an address, wherever its segments were cut."""
    for segment in image.segments:
        if segment.address <= address and address + length <= segment.end:
            start = address - segment.address
            return segment.data[start : start + length]
    raise AssertionError(f"nothing at {address:08X}+{length} in {image.summary()}")


def make_elf(sections, entry: int = 0, bss: tuple[int, int] | None = None) -> bytes:
    """A small 32-bit little-endian Arm ELF, written out by hand.

    `sections` is (name, load address, run address, bytes) for each, every one
    in a loadable segment of its own -- which is how a linker lays out data
    that is stored in flash and run from RAM. `bss` is (address, size) for a
    section that takes up memory and no room in the file.
    """
    names = b"\0"
    offsets = {}
    for name in [s[0] for s in sections] + ([".bss"] if bss else []) + [".shstrtab"]:
        offsets[name] = len(names)
        names += name.encode() + b"\0"

    program_headers = len(sections) + (1 if bss else 0)
    position = 52 + 32 * program_headers
    placed = []
    for name, load, run, data in sections:
        placed.append((name, load, run, data, position))
        position += len(data)
    names_at = position
    position += len(names)
    sections_at = position

    out = bytearray()
    out += b"\x7fELF" + bytes([1, 1, 1]) + bytes(9)  # 32-bit, little-endian
    section_count = 1 + len(sections) + (1 if bss else 0) + 1
    out += struct.pack(
        "<HHIIIIIHHHHHH",
        2,  # an executable
        40,  # Arm
        1,
        entry,
        52,  # program headers follow this header
        sections_at,
        0,
        52,
        32,
        program_headers,
        40,
        section_count,
        section_count - 1,  # the names are the last section
    )
    for _name, load, run, data, offset in placed:
        out += struct.pack("<IIIIIIII", 1, offset, run, load, len(data), len(data), 5, 4)
    if bss:
        out += struct.pack("<IIIIIIII", 1, names_at, bss[0], bss[0], 0, bss[1], 6, 4)
    for _name, _load, _run, data, _offset in placed:
        out += data
    out += names

    out += bytes(40)  # the null section every ELF starts with
    for name, _load, run, data, offset in placed:
        # PROGBITS, allocated: what a programmer is for.
        out += struct.pack("<IIIIIIIIII", offsets[name], 1, 2, run, offset, len(data), 0, 0, 4, 0)
    if bss:
        # NOBITS: memory to be cleared at start-up, with nothing to program.
        out += struct.pack(
            "<IIIIIIIIII", offsets[".bss"], 8, 3, bss[0], names_at, bss[1], 0, 0, 4, 0
        )
    out += struct.pack(
        "<IIIIIIIIII", offsets[".shstrtab"], 3, 0, 0, names_at, len(names), 0, 0, 1, 0
    )
    return bytes(out)


def binfile() -> bincopy.BinFile:
    made = bincopy.BinFile()
    made.add_binary(CODE, address=0x0800_0000)
    made.add_binary(DATA, address=0x0800_4000)
    return made


# --- the formats ----------------------------------------------------------------------
def test_intel_hex_keeps_its_addresses_and_its_gaps(tmp_path):
    path = tmp_path / "app.hex"
    path.write_text(binfile().as_ihex())
    image = images.read(str(path))
    assert image.format == images.IHEX
    assert [(s.address, len(s)) for s in image.segments] == [(0x0800_0000, 256), (0x0800_4000, 32)]
    assert at(image, 0x0800_0000, 256) == CODE
    assert at(image, 0x0800_4000, 32) == DATA
    assert image.size == 288, "the gap between them is not part of the file"


def test_s_record_is_read_to_the_same_thing(tmp_path):
    """The format pyOCD does not read, and the reason every format is read here."""
    hexed, srec = tmp_path / "app.hex", tmp_path / "app.s37"
    hexed.write_text(binfile().as_ihex())
    srec.write_text(binfile().as_srec(address_length_bits=32))
    image = images.read(str(srec))
    assert image.format == images.SREC
    assert image.segments == images.read(str(hexed)).segments


def test_a_raw_binary_goes_where_it_is_told(tmp_path):
    path = tmp_path / "app.bin"
    path.write_bytes(CODE)
    image = images.read(str(path), address=0x1000_0000)
    assert image.format == images.BINARY
    assert image.segments == (images.Segment(0x1000_0000, CODE),)
    assert image.entry is None


def test_a_raw_binary_with_no_address_is_refused_rather_than_put_at_zero(tmp_path):
    path = tmp_path / "app.bin"
    path.write_bytes(CODE)
    with pytest.raises(ImageError, match="start address"):
        images.read(str(path))


def test_an_address_typed_for_a_file_that_has_its_own_is_ignored(tmp_path):
    path = tmp_path / "app.hex"
    path.write_text(binfile().as_ihex())
    assert images.read(str(path), address=0x1234).address == 0x0800_0000


def test_the_format_comes_from_the_contents_and_not_the_name(tmp_path):
    path = tmp_path / "firmware.txt"
    path.write_text(binfile().as_srec())
    assert images.read(str(path)).format == images.SREC
    assert not images.looks_binary(str(path))
    assert images.looks_binary("build/app.BIN")


def test_lines_of_a_hex_file_that_are_not_records_are_counted_and_said(tmp_path):
    path = tmp_path / "app.hex"
    path.write_text("; built on a Tuesday\n" + binfile().as_ihex())
    image = images.read(str(path))
    assert image.ignored == 1
    assert at(image, 0x0800_0000, 256) == CODE
    assert "1 line not starting with ':' ignored" in image.summary()


# --- ELF ------------------------------------------------------------------------------
def test_an_elf_is_read_at_its_load_addresses(tmp_path):
    """Initialised data is stored in flash and run from RAM. It has to be
    programmed where it is stored: at its run address there is only RAM."""
    path = tmp_path / "app.elf"
    path.write_bytes(
        make_elf(
            [
                (".text", 0x0800_0000, 0x0800_0000, CODE),
                (".data", 0x0800_0100, 0x2000_0000, DATA),
            ],
            entry=0x0800_00C1,
        )
    )
    image = images.read(str(path))
    assert image.format == images.ELF
    assert at(image, 0x0800_0000, 256) == CODE
    assert at(image, 0x0800_0100, 32) == DATA
    assert all(s.address < 0x2000_0000 for s in image.segments), "nothing at the run address"
    assert image.entry == 0x0800_00C1


def test_memory_that_is_only_cleared_is_not_something_to_program(tmp_path):
    path = tmp_path / "app.elf"
    path.write_bytes(
        make_elf([(".text", 0x0800_0000, 0x0800_0000, CODE)], bss=(0x2000_0000, 0x400))
    )
    image = images.read(str(path))
    assert image.size == len(CODE)
    assert [s.address for s in image.segments] == [0x0800_0000]


def test_an_elf_is_known_by_how_it_starts(tmp_path):
    path = tmp_path / "firmware"
    path.write_bytes(make_elf([(".text", 0x0800_0000, 0x0800_0000, CODE)]))
    assert images.read(str(path)).format == images.ELF


def test_an_elf_with_nothing_to_load_says_so(tmp_path):
    path = tmp_path / "empty.elf"
    path.write_bytes(make_elf([], bss=(0x2000_0000, 16)))
    with pytest.raises(ImageError, match="nothing in it to program"):
        images.read(str(path))


# --- files that cannot be read --------------------------------------------------------
def test_a_damaged_elf_is_an_image_error_and_not_a_traceback(tmp_path):
    path = tmp_path / "app.elf"
    path.write_bytes(make_elf([(".text", 0x0800_0000, 0x0800_0000, CODE)])[:40])
    with pytest.raises(ImageError, match="not readable as ELF"):
        images.read(str(path))


def test_a_hex_file_with_a_bad_checksum_is_refused(tmp_path):
    path = tmp_path / "app.hex"
    lines = binfile().as_ihex().splitlines()
    lines[1] = lines[1][:-2] + ("00" if lines[1][-2:] != "00" else "01")
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ImageError, match="not readable as Intel HEX"):
        images.read(str(path))


def test_an_empty_file_and_a_missing_one_each_say_which(tmp_path):
    empty = tmp_path / "empty.hex"
    empty.write_bytes(b"")
    with pytest.raises(ImageError, match="empty"):
        images.read(str(empty))
    with pytest.raises(ImageError):
        images.read(str(tmp_path / "not-there.hex"))


def test_the_summary_says_what_was_read_and_where_it_goes(tmp_path):
    path = tmp_path / "app.hex"
    path.write_text(binfile().as_ihex())
    said = images.read(str(path)).summary()
    assert said == "app.hex: Intel HEX, 288 bytes, 2 segments [08000000+256, 08004000+32]"
