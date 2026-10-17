# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What will be written where, worked out before anything is sent."""

from pyflashgui.core.events import ERROR, WARNING
from pyflashgui.core.images import BINARY, Image, Segment
from pyflashgui.core.memory_map import FLASH, GENERIC, RAM, ROM, Region, lay_out

FLASH_REGION = Region("flash", 0x0800_0000, 0x1_0000, FLASH, sector_size=0x1000, page_size=0x100)
RAM_REGION = Region("ram", 0x2000_0000, 0x4000, RAM)
ROM_REGION = Region("bootrom", 0x0000_0000, 0x1000, ROM)
MIRROR = Region("flash_mirror", 0x0900_0000, 0x1_0000, ROM, alias_of="flash")
REGIONS = (ROM_REGION, FLASH_REGION, MIRROR, RAM_REGION)


def image(name: str, *runs: tuple[int, int]) -> Image:
    """An image of this name with a run of bytes at each (address, length)."""
    return Image(name, BINARY, tuple(Segment(a, bytes(n)) for a, n in runs))


def messages(layout, level=None) -> list[str]:
    return [p.message for p in layout.problems if level is None or p.level == level]


def test_a_file_that_fits_has_nothing_wrong_with_it():
    layout = lay_out([image("app.hex", (0x0800_0000, 0x1800))], REGIONS)
    assert layout.checked and layout.programmable and not layout.problems
    (piece,) = layout.pieces
    assert (piece.source, piece.address, piece.length) == ("app.hex", 0x0800_0000, 0x1800)
    assert piece.region is FLASH_REGION


def test_usage_counts_the_bytes_written_and_the_sectors_erased_for_them():
    """A byte in a sector costs the whole sector: that is what is erased."""
    layout = lay_out([image("app.hex", (0x0800_0000, 0x1001), (0x0800_8000, 0x10))], REGIONS)
    (usage,) = layout.usage
    assert usage.region is FLASH_REGION
    assert usage.used == 0x1011
    assert usage.sectors == 3, "two for the first run, which is one byte into its second"
    assert usage.erased == 0x3000
    assert usage.fraction == 0x1011 / 0x1_0000


def test_a_file_running_off_the_end_of_flash_is_cut_there_and_the_rest_is_an_error():
    layout = lay_out([image("big.bin", (0x0800_F000, 0x2000))], REGIONS)
    inside, outside = layout.pieces
    assert (inside.address, inside.length, inside.region) == (0x0800_F000, 0x1000, FLASH_REGION)
    assert (outside.address, outside.length, outside.region) == (0x0801_0000, 0x1000, None)
    assert not layout.programmable
    assert messages(layout, ERROR) == [
        "big.bin: 4096 bytes at 08010000 to 08010FFF are outside the target's memory."
    ]


def test_a_file_linked_for_another_part_is_an_error_before_anything_is_sent():
    layout = lay_out([image("wrong.hex", (0x1000_0000, 0x400))], REGIONS)
    assert not layout.programmable
    assert "outside the target's memory" in messages(layout)[0]
    assert not layout.usage, "and none of it counts as flash used"


def test_bytes_for_ram_are_a_warning_and_not_a_refusal():
    """Loading into RAM to run from it is a real thing to do."""
    layout = lay_out([image("ram.elf", (0x2000_0000, 0x100))], REGIONS)
    assert layout.programmable
    assert messages(layout, WARNING) == [
        "ram.elf: 256 bytes at 20000000 to 200000FF go to RAM (ram), not flash: "
        "written there, they stay on the device only until it is next reset."
    ]


def test_a_target_that_is_only_the_cortex_m_address_map_cannot_program():
    """Reported: with pyOCD's cortex_m chosen, a file for an XMC4500's flash
    was said to be in RAM and lost at the next reset -- read as the file
    being lost. The map calls that RAM only because it may be."""
    generic = (
        Region("Code", 0x0000_0000, 0x2000_0000, GENERIC),
        Region("SRAM", 0x2000_0000, 0x2000_0000, GENERIC),
    )
    layout = lay_out(
        [image("app.hex", (0x0C00_0000, 0x100)), image("more.hex", (0x0C01_0000, 0x100))],
        generic,
    )
    assert not layout.programmable
    (said,) = messages(layout)
    assert said.startswith("app.hex, more.hex: the target chosen is no device in particular")
    assert "RAM" not in said and "Tools > pyOCD device packs" in said
    assert not layout.usage


def test_memory_that_cannot_be_written_is_an_error():
    layout = lay_out([image("rom.bin", (0x0000_0000, 0x10))], REGIONS)
    assert messages(layout, ERROR) == [
        "rom.bin: 16 bytes at 00000000 to 0000000F are in bootrom, which cannot be written."
    ]


def test_another_address_for_the_flash_is_named_as_that():
    """A device may show its flash at several addresses and take writes at one."""
    layout = lay_out([image("app.hex", (0x0900_0000, 0x10))], REGIONS)
    assert messages(layout, ERROR) == [
        "app.hex: 16 bytes at 09000000 to 0900000F are in flash_mirror, which is another "
        "address for flash and cannot be programmed through."
    ]


def test_two_files_that_claim_the_same_bytes_are_an_error():
    layout = lay_out(
        [
            image("boot.hex", (0x0800_0000, 0x2000)),
            image("app.hex", (0x0800_1000, 0x2000)),
        ],
        REGIONS,
    )
    assert not layout.programmable
    assert messages(layout, ERROR) == ["boot.hex and app.hex both write 08001000 to 08001FFF."]


def test_files_side_by_side_do_not_overlap():
    layout = lay_out(
        [
            image("boot.hex", (0x0800_0000, 0x1000)),
            image("app.hex", (0x0800_1000, 0x1000)),
        ],
        REGIONS,
    )
    assert layout.programmable and not layout.problems
    assert layout.usage[0].used == 0x2000 and layout.usage[0].sectors == 2


def test_a_run_inside_a_longer_one_is_still_found():
    """The longer run is the one to compare the next against, not the last seen."""
    layout = lay_out(
        [
            image("all.hex", (0x0800_0000, 0x4000)),
            image("a.hex", (0x0800_0100, 0x10)),
            image("b.hex", (0x0800_2000, 0x10)),
        ],
        REGIONS,
    )
    assert messages(layout, ERROR) == [
        "all.hex and a.hex both write 08000100 to 0800010F.",
        "all.hex and b.hex both write 08002000 to 0800200F.",
    ]


def test_with_no_memory_known_the_pieces_are_listed_and_nothing_is_called_wrong():
    """A target whose memory is only known once it is connected to."""
    layout = lay_out([image("app.hex", (0x0800_0000, 0x100), (0x9000_0000, 0x10))], [])
    assert not layout.checked
    assert layout.programmable and not layout.problems and not layout.usage
    assert [(p.address, p.length, p.region) for p in layout.pieces] == [
        (0x0800_0000, 0x100, None),
        (0x9000_0000, 0x10, None),
    ]


def test_overlaps_are_found_even_with_no_memory_known():
    layout = lay_out(
        [image("a.hex", (0x0800_0000, 0x100)), image("b.hex", (0x0800_0080, 0x100))], []
    )
    assert not layout.programmable
    assert messages(layout) == ["a.hex and b.hex both write 08000080 to 080000FF."]


def test_a_run_across_a_gap_between_regions_is_cut_at_both_edges():
    low = Region("low", 0x1000, 0x1000, FLASH, sector_size=0x100)
    high = Region("high", 0x3000, 0x1000, FLASH, sector_size=0x100)
    layout = lay_out([image("span.bin", (0x1F00, 0x1200))], [low, high])
    assert [(p.address, p.length, p.region) for p in layout.pieces] == [
        (0x1F00, 0x100, low),
        (0x2000, 0x1000, None),
        (0x3000, 0x100, high),
    ]
    assert [u.used for u in layout.usage] == [0x100, 0x100]
