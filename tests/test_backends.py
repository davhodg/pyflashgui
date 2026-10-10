# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Backends: the interface, the simulated one behind it, and what of pyOCD's
can be asked without a probe plugged in."""

import pytest

from pyflashgui import backends
from pyflashgui.backends.base import (
    ERASE_CHIP,
    VERIFY_CHUNK,
    BackendError,
    CancelledError,
)
from pyflashgui.backends.simulated import SimulatedBackend
from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import FLASH, RAM, lay_out

PROBE = "SIM0001"
FLASH_AT = 0x0800_0000
RAM_AT = 0x2000_0000


@pytest.fixture
def backend():
    return SimulatedBackend()


@pytest.fixture
def connection(backend):
    with backend.connect(PROBE, "sim_single") as made:
        yield made


def pattern(length: int, seed: int = 0) -> bytes:
    return bytes((seed + i) % 251 for i in range(length))


# --- what is there --------------------------------------------------------------------
def test_a_backend_says_what_is_plugged_in_and_what_it_can_program(backend):
    assert [p.unique_id for p in backend.probes()] == ["SIM0001", "SIM0002"]
    assert {t.name for t in backend.targets()} == {"sim_single", "sim_dual"}
    flash, ram = backend.regions("sim_single")
    assert (flash.kind, flash.sector_size) == (FLASH, 0x1000)
    assert ram.kind == RAM
    assert backend.regions("no_such_part") == []


def test_connecting_to_what_is_not_there_says_which(backend):
    with pytest.raises(BackendError, match="no probe with the id NOPE"):
        backend.connect("NOPE", "sim_single")
    with pytest.raises(BackendError, match="not a target"):
        backend.connect(PROBE, "stm32f999")


def test_a_probe_is_connected_once_at_a_time(backend):
    first = backend.connect(PROBE, "sim_single")
    with pytest.raises(BackendError, match="already connected"):
        backend.connect(PROBE, "sim_single")
    backend.connect("SIM0002", "sim_single").close()  # another probe is another matter
    first.close()
    first.close()  # twice is allowed
    backend.connect(PROBE, "sim_single").close()


def test_a_closed_connection_refuses_rather_than_pretends(backend):
    connection = backend.connect(PROBE, "sim_single")
    connection.close()
    with pytest.raises(BackendError, match="closed"):
        connection.read(FLASH_AT, 4)
    with pytest.raises(BackendError, match="closed"):
        connection.program([Segment(FLASH_AT, b"\x01")])


# --- programming ----------------------------------------------------------------------
def test_erased_flash_reads_as_ff(connection):
    assert connection.read(FLASH_AT, 16) == b"\xff" * 16
    assert connection.read(RAM_AT, 4) == bytes(4)


def test_what_is_programmed_is_what_is_read_back(connection):
    data = pattern(0x2345)
    seen = []
    connection.program([Segment(FLASH_AT + 0x100, data)], progress=seen.append)
    assert connection.read(FLASH_AT + 0x100, len(data)) == data
    assert seen and seen[-1] == 1.0
    assert seen == sorted(seen), "progress never goes backwards"


def test_a_sector_is_erased_whole_and_its_neighbours_are_left(connection):
    connection.program([Segment(FLASH_AT, pattern(0x3000))])
    connection.program([Segment(FLASH_AT + 0x1800, b"\xaa" * 4)])
    assert connection.read(FLASH_AT, 0x1000) == pattern(0x1000), "the sector before"
    assert connection.read(FLASH_AT + 0x1000, 0x800) == b"\xff" * 0x800, "the rest of its own"
    assert connection.read(FLASH_AT + 0x1800, 4) == b"\xaa" * 4
    assert connection.read(FLASH_AT + 0x2000, 0x1000) == pattern(0x1000, 0x2000 % 251)


def test_erasing_the_chip_first_leaves_nothing_of_what_was_there(connection):
    connection.program([Segment(FLASH_AT + 0x8000, pattern(64))])
    connection.program([Segment(FLASH_AT, b"\x55" * 8)], erase=ERASE_CHIP)
    assert connection.read(FLASH_AT, 8) == b"\x55" * 8
    assert connection.read(FLASH_AT + 0x8000, 64) == b"\xff" * 64


def test_erase_chip_by_itself(connection):
    connection.program([Segment(FLASH_AT, pattern(64))])
    connection.erase_chip()
    assert connection.read(FLASH_AT, 64) == b"\xff" * 64


def test_a_file_that_does_not_fit_leaves_the_target_as_it_was(connection):
    connection.program([Segment(FLASH_AT, pattern(64))])
    too_far = [Segment(FLASH_AT, b"\x00" * 64), Segment(0x4000_0000, b"\x00")]
    with pytest.raises(BackendError, match="no memory at 40000000"):
        connection.program(too_far)
    assert connection.read(FLASH_AT, 64) == pattern(64)


def test_flash_outlives_a_connection_and_a_reset_and_ram_does_not(backend):
    with backend.connect(PROBE, "sim_single") as connection:
        connection.program([Segment(FLASH_AT, b"kept"), Segment(RAM_AT, b"lost")])
        assert connection.read(RAM_AT, 4) == b"lost"
        connection.reset()
        assert connection.read(RAM_AT, 4) == bytes(4)
    with backend.connect(PROBE, "sim_single") as again:
        assert again.read(FLASH_AT, 4) == b"kept"
    assert backend.board(PROBE).resets == 1


def test_another_address_for_the_flash_reads_the_same_and_takes_no_writes(backend):
    with backend.connect(PROBE, "sim_dual") as connection:
        connection.program([Segment(0x1000_0000, b"here")])
        assert connection.read(0x1100_0000, 4) == b"here"
        with pytest.raises(BackendError, match="application_mirror"):
            connection.program([Segment(0x1100_0000, b"nope")])


# --- verifying ------------------------------------------------------------------------
def test_verifying_what_was_just_programmed_passes(connection):
    segments = [Segment(FLASH_AT, pattern(VERIFY_CHUNK * 2 + 17)), Segment(FLASH_AT + 0x8000, b"x")]
    connection.program(segments)
    seen = []
    result = connection.verify(segments, progress=seen.append)
    assert result.ok and result.first is None
    assert result.checked == VERIFY_CHUNK * 2 + 18
    assert seen[-1] == 1.0 and seen == sorted(seen)


def test_a_byte_that_did_not_take_is_found_and_named(backend, connection):
    data = pattern(VERIFY_CHUNK + 100)
    connection.program([Segment(FLASH_AT, data)])
    flash = backend.board(PROBE).memory["flash"]
    for offset in (VERIFY_CHUNK + 5, VERIFY_CHUNK + 50):
        flash[offset] ^= 0xFF
    result = connection.verify([Segment(FLASH_AT, data)])
    assert not result.ok
    assert result.different == 2
    address, wanted, found = result.first
    assert address == FLASH_AT + VERIFY_CHUNK + 5
    assert wanted == data[VERIFY_CHUNK + 5] and found == wanted ^ 0xFF


def test_verifying_stops_when_it_is_asked_to(connection):
    segments = [Segment(FLASH_AT, pattern(VERIFY_CHUNK * 4))]
    connection.program(segments)
    asked = []

    def cancelled() -> bool:
        asked.append(1)
        return len(asked) > 2

    with pytest.raises(CancelledError):
        connection.verify(segments, cancelled=cancelled)
    assert len(asked) == 3, "asked before each read, and stopped at the first yes"


# --- with the memory map --------------------------------------------------------------
def test_what_the_map_calls_programmable_the_backend_programs(backend, tmp_path):
    """The map and the programming are given the same bytes, so they agree."""
    import bincopy

    from pyflashgui.core import images

    made = bincopy.BinFile()
    made.add_binary(pattern(0x1800), address=FLASH_AT)
    path = tmp_path / "app.s37"
    path.write_text(made.as_srec(address_length_bits=32))
    image = images.read(str(path))

    layout = lay_out([image], backend.regions("sim_single"))
    assert layout.programmable and layout.usage[0].sectors == 2
    with backend.connect(PROBE, "sim_single") as connection:
        connection.program(image.segments)
        assert connection.verify(image.segments).ok


# --- by name --------------------------------------------------------------------------
def test_there_is_one_of_each_backend(monkeypatch):
    monkeypatch.setattr(backends, "_made", {})
    assert backends.get("simulated") is backends.get("simulated")
    assert backends.get().name == backends.DEFAULT == "pyocd"
    assert [backends.get(name).name for name in backends.NAMES] == list(backends.NAMES)
    with pytest.raises(BackendError, match="no backend called openocd"):
        backends.get("openocd")


# --- pyOCD, as far as it goes with nothing plugged in ---------------------------------
def test_pyocd_lists_its_targets_and_the_memory_of_a_built_in_one():
    pyocd = backends.get("pyocd")
    names = {t.name: t for t in pyocd.targets()}
    assert "rp2350" in names and names["rp2350"].source == "built in"
    assert names["rp2350"].vendor == "Raspberry Pi"

    regions = pyocd.regions("rp2350")
    flash = next(r for r in regions if r.kind == FLASH)
    assert (flash.name, flash.start, flash.sector_size, flash.page_size) == (
        "xip",
        0x1000_0000,
        4096,
        256,
    )
    assert [r.start for r in regions] == sorted(r.start for r in regions)
    mirror = next(r for r in regions if r.name == "xip_noalloc")
    assert mirror.alias_of == "xip", "and the memory map will say so"
    assert pyocd.regions("no_such_part") == []


def test_a_file_linked_for_the_wrong_address_of_a_real_part_is_caught_by_the_map():
    """pyOCD's own map of a built-in target, through pyflashgui's check."""
    from pyflashgui.core.images import BINARY, Image

    regions = backends.get("pyocd").regions("rp2350")
    good = Image("app.bin", BINARY, (Segment(0x1000_0000, bytes(0x2000)),))
    bad = Image("app.bin", BINARY, (Segment(0x1100_0000, bytes(16)),))
    assert lay_out([good], regions).programmable
    assert "another address for xip" in lay_out([bad], regions).problems[0].message


def test_pyocd_refuses_a_probe_that_is_not_plugged_in():
    with pytest.raises(BackendError, match="not plugged in"):
        backends.get("pyocd").connect("no-such-probe-0000", "rp2350")
