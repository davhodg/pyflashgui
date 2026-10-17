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
def test_ram_is_written_as_it_is_and_flash_is_not_written_to(connection):
    ram = next(r for r in connection.regions() if r.kind == RAM)
    connection.write(ram.start + 4, b"abc")
    assert connection.read(ram.start, 8) == b"\x00" * 4 + b"abc\x00"
    flash = next(r for r in connection.regions() if r.kind == FLASH)
    with pytest.raises(BackendError, match="is flash: program it instead"):
        connection.write(flash.start, b"x")


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


def test_an_xds110_is_asked_for_one_reply_at_a_time():
    """pyOCD's own advice for that probe's firmware; nothing else is slowed."""
    from pyflashgui.backends.pyocd_backend import needs_one_packet_at_a_time

    assert needs_one_packet_at_a_time("Texas Instruments XDS110 (03.00.00.25)", None)
    assert needs_one_packet_at_a_time(None, "XDS110 with CMSIS-DAP")
    assert not needs_one_packet_at_a_time("Raspberry Pi Debug Probe (CMSIS-DAP)", "Debug Probe")


def test_a_pyocd_connect_that_fails_lets_go_of_the_probe(monkeypatch):
    """Reported: after one failed connect every later one failed, until switching
    backend and back: the session that failed to open still held the probe."""
    from pyocd.core import helpers, session

    class Probe:
        unique_id = "PROBE1"
        description = "Some probe"
        product_name = "Some probe"

    closed = []

    class Session:
        def __init__(self, probe, auto_open=False, options=None):
            self.options = options or {}

        def open(self):
            raise RuntimeError("no answer from the target")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(helpers.ConnectHelper, "get_all_connected_probes", lambda **_kw: [Probe()])
    monkeypatch.setattr(session, "Session", Session)
    with pytest.raises(BackendError, match="no answer from the target"):
        backends.get("pyocd").connect("PROBE1", "cortex_m")
    assert closed == [True]


def test_a_debug_clock_is_said_as_somebody_would_say_it():
    from pyflashgui.backends.pyocd_backend import speed_text

    assert speed_text(1_000_000) == "1 MHz"
    assert speed_text(4_000_000) == "4 MHz"
    assert speed_text(400_000) == "400 kHz"
    assert speed_text(None) == ""


def test_each_backend_says_what_leaving_the_speed_to_it_comes_to():
    assert backends.get("pyocd").default_speed == "Default (1 MHz)"
    assert backends.get("jlink").default_speed == "Default (auto)"


@pytest.fixture
def fake_pyocd(monkeypatch):
    """pyOCD with a J-Link plugged in, and a Session that records what it was given."""
    from pyocd.core import helpers, session

    from pyflashgui.backends import pyocd_backend

    class Probe:
        unique_id = "JLINK1"
        description = "J-Link"
        product_name = "J-Link"

    made = {"options": [], "refuse": None}

    class Session:
        def __init__(self, probe, auto_open=False, options=None):
            self.options = dict(options or {})
            made["options"].append(self.options)

        def open(self):
            if made["refuse"] is not None and made["refuse"](self.options):
                raise RuntimeError("SEGGER's library did not take that")

        def close(self):
            pass

    monkeypatch.setattr(helpers.ConnectHelper, "get_all_connected_probes", lambda **_kw: [Probe()])
    monkeypatch.setattr(session, "Session", Session)
    monkeypatch.setattr(pyocd_backend, "is_jlink", lambda _probe: True)
    return made


def test_a_jlink_through_pyocd_is_named_the_core_so_it_reads_in_blocks(fake_pyocd, monkeypatch):
    from pyflashgui.backends import pyocd_packs

    monkeypatch.setattr(pyocd_packs, "core_of", lambda target: "Cortex-M4")
    connection = backends.get("pyocd").connect("JLINK1", "xmc4500-f100x1024")
    assert fake_pyocd["options"][-1]["jlink.device"] == "Cortex-M4"
    assert connection.notes == ()


def test_a_jlink_that_does_not_take_the_name_connects_the_slow_way_and_says_so(
    fake_pyocd, monkeypatch
):
    from pyflashgui.backends import pyocd_backend, pyocd_packs

    monkeypatch.setattr(pyocd_packs, "core_of", lambda target: "Cortex-M4")
    fake_pyocd["refuse"] = lambda options: "jlink.device" in options
    connection = backends.get("pyocd").connect("JLINK1", "xmc4500-f100x1024")
    assert "jlink.device" not in fake_pyocd["options"][-1]
    assert connection.notes == (pyocd_backend.SLOW_JLINK,)


def test_a_jlink_for_a_target_with_no_pack_says_it_is_slow(fake_pyocd, monkeypatch):
    from pyflashgui.backends import pyocd_backend, pyocd_packs

    monkeypatch.setattr(pyocd_packs, "core_of", lambda target: "")
    connection = backends.get("pyocd").connect("JLINK1", "rp2350")
    assert "jlink.device" not in fake_pyocd["options"][-1]
    assert connection.notes == (pyocd_backend.SLOW_JLINK,)


def test_pyocd_s_cortex_m_is_known_as_no_device_in_particular():
    from pyocd.coresight.coresight_target import CoreSightTarget

    from pyflashgui.backends.pyocd_backend import is_generic, regions_of
    from pyflashgui.core.memory_map import GENERIC

    class Device(CoreSightTarget):
        pass

    assert is_generic(object.__new__(CoreSightTarget))
    assert not is_generic(object.__new__(Device)), "a device of its own has its own map"
    # The map pyOCD makes up for it on connecting, as pyOCD makes it.
    made = CoreSightTarget._create_default_cortex_m_memory_map(None)
    assert {r.kind for r in regions_of(made, generic=True)} == {GENERIC}
    assert {r.kind for r in regions_of(made)} != {GENERIC}


def test_pyocd_s_erasing_then_programming_is_said_as_two_stages():
    """Reported on an XMC4500: the bar ran through Programming twice, the
    first time pyOCD erasing the sectors it was about to write."""
    from pyflashgui.backends.pyocd_backend import _stages

    said = []
    report = _stages(lambda fraction, doing: said.append((doing, fraction)))
    for fraction in (0.0, 0.25, 0.5, 0.5, 1.0, 0.0, 0.5, 1.0):  # two regions' worth of erasing
        report(fraction)
    assert [d for d, _f in said] == ["Erasing"] * 5 + ["Programming"] * 3
    assert said[-1] == ("Programming", 1.0)


def test_a_pyocd_disconnect_that_fails_still_lets_go_of_the_probe():
    """Reported: with the board's power turned off while connected, every
    connect after said "No emulator with serial number" though Find probes
    found the J-Link. pyOCD gave up closing at the target and never closed
    the probe, which SEGGER's library went on holding."""
    from pyflashgui.backends.pyocd_backend import PyocdConnection

    class Probe:
        is_open = True

        def close(self):
            self.is_open = False

    class Session:
        probe = Probe()

        def close(self):
            raise RuntimeError("Unspecified error")

    session = Session()
    connection = PyocdConnection(session)
    with pytest.raises(BackendError, match=r"did not answer \(Unspecified error\)"):
        connection.close()
    assert not session.probe.is_open


@pytest.mark.parametrize(
    ("kind", "asked"),
    [("default", None), ("pin", "HARDWARE"), ("system", "SYSTEM"), ("core", "CORE")],
)
def test_each_way_of_resetting_is_the_pyocd_reset_type_of_that_name(kind, asked):
    from pyocd.core.target import Target

    from pyflashgui.backends.pyocd_backend import PyocdConnection

    class FakeTarget:
        def reset(self, reset_type=None):
            self.asked = reset_type

        def read32(self, address):
            return 0x410FC241  # answers after the reset

    class Session:
        target = FakeTarget()

    PyocdConnection(Session()).reset(kind=kind)
    assert Session.target.asked == (getattr(Target.ResetType, asked) if asked else None)


def test_j_link_commander_resets_only_its_own_way():
    from pyflashgui.backends.jlink_backend import JLinkBackend

    assert JLinkBackend.reset_kinds == ("default",)


def test_a_pack_device_spelt_pyocd_s_way_is_the_same_device(fake_pyocd, monkeypatch):
    """Reported: chosen as xmc4500_f100x1024 -- pyOCD's spelling, in its list
    once the pack had been used -- a J-Link was not named the core, and
    worked a word at a time."""
    from pyflashgui.backends import pyocd_packs

    class Device:
        part_number = "XMC4500-F100x1024"

        def __init__(self):
            self.processors_map = {"Cortex-M4": None}

    from pyocd.target.pack import pack_target

    monkeypatch.setattr(pyocd_packs, "packs_for", lambda target: [])
    monkeypatch.setattr(pack_target.ManagedPacks, "get_installed_targets", lambda: [Device()])
    assert pyocd_packs.core_of("xmc4500_f100x1024") == "Cortex-M4"
    connection = backends.get("pyocd").connect("JLINK1", "xmc4500_f100x1024")
    assert fake_pyocd["options"][-1]["jlink.device"] == "Cortex-M4"
    assert connection.notes == ()


def test_a_pack_device_pyocd_has_taken_in_is_listed_once(monkeypatch):
    from pyocd.target import TARGET
    from pyocd.target.pack import pack_target

    from pyflashgui.backends.pyocd_backend import PyocdBackend

    class Device:
        part_number = "XMC4500-F100x1024"
        vendor = "Infineon:7"

    made = type("Xmc4500_f100x1024", (), {"_pack_device": Device()})
    monkeypatch.setitem(TARGET, "xmc4500_f100x1024", made)
    monkeypatch.setattr(pack_target.ManagedPacks, "get_installed_targets", lambda: [Device()])
    monkeypatch.setattr(PyocdBackend, "_file_devices", staticmethod(lambda: []))
    names = [t.name for t in PyocdBackend().targets() if "xmc4500" in t.name]
    assert names == ["xmc4500-f100x1024"]


def test_a_reset_that_takes_the_connection_with_it_connects_again(monkeypatch):
    from pyflashgui.backends import pyocd_backend

    monkeypatch.setattr(pyocd_backend.time, "sleep", lambda _s: None)
    """Reported on an XMC4500 through a J-Link: after a reset by its pin it
    still said connected, and every operation failed with "Unspecified
    error"."""
    from pyflashgui.backends.pyocd_backend import PyocdConnection

    class Target:
        def __init__(self, answers):
            self.answers = answers

        def reset(self, reset_type=None):
            self.answers = False  # the debug port went with it

        def read32(self, address):
            if not self.answers:
                raise RuntimeError("Unspecified error")
            return 0x410FC241

    class Session:
        def __init__(self, answers):
            self.target = Target(answers)
            self.closed = False

        def close(self):
            self.closed = True

    old, new = Session(True), Session(True)
    connection = PyocdConnection(old, reopen=lambda: new)
    said = connection.reset(kind="pin")
    assert said == (
        "The reset took the debug connection with it: connected again, leaving the target running."
    )
    assert old.closed, "the lost session let go of"
    assert connection._session is new
    assert connection._answers()


def test_a_reset_that_leaves_the_connection_keeps_it():
    from pyflashgui.backends.pyocd_backend import PyocdConnection

    class Target:
        def reset(self, reset_type=None):
            pass

        def read32(self, address):
            return 0x410FC241

    class Session:
        target = Target()

    reopened = []
    connection = PyocdConnection(Session(), reopen=lambda: reopened.append(1))
    assert connection.reset(kind="system") is None, "nothing to say"
    assert reopened == []


@pytest.mark.parametrize(("stop", "mode"), [(True, "halt"), (False, "attach")])
def test_pyocd_is_told_whether_to_stop_the_target_on_connecting(
    fake_pyocd, monkeypatch, stop, mode
):
    from pyflashgui.backends import pyocd_packs

    monkeypatch.setattr(pyocd_packs, "core_of", lambda target: "Cortex-M4")
    backends.get("pyocd").connect("JLINK1", "xmc4500-f100x1024", stop=stop)
    assert fake_pyocd["options"][-1]["connect_mode"] == mode


def test_a_target_still_starting_after_its_reset_is_waited_for(monkeypatch):
    """Reported: connecting again straight after a reset by the pin failed,
    though the connection had not been lost -- the device was still starting."""
    from pyflashgui.backends import pyocd_backend
    from pyflashgui.backends.pyocd_backend import PyocdConnection

    waited = []
    monkeypatch.setattr(pyocd_backend.time, "sleep", waited.append)

    class Target:
        silent = 0

        def reset(self, reset_type=None):
            self.silent = 2  # answers on the third time of asking

        def read32(self, address):
            if self.silent:
                self.silent -= 1
                raise RuntimeError("Unspecified error")
            return 0x410FC241

    class Session:
        target = Target()

    reopened = []
    connection = PyocdConnection(Session(), reopen=lambda: reopened.append(1))
    assert connection.reset(kind="pin") is None
    assert reopened == [], "a target that answers in the end is not connected to again"
    assert waited[0] >= 0.1, "never asked at once"


def test_connecting_again_is_tried_more_than_once(monkeypatch):
    from pyflashgui.backends import pyocd_backend
    from pyflashgui.backends.pyocd_backend import PyocdConnection

    monkeypatch.setattr(pyocd_backend.time, "sleep", lambda _s: None)

    class Target:
        def reset(self, reset_type=None):
            pass

        def read32(self, address):
            raise RuntimeError("Unspecified error")

    class Session:
        target = Target()

        def close(self):
            pass

    class Fresh:
        class target:  # noqa: N801 -- standing in for an attribute
            pass

    attempts = []

    def reopen():
        attempts.append(1)
        if len(attempts) < 3:
            raise BackendError("Target is not connected neither coresight is not configured")
        return Fresh()

    connection = PyocdConnection(Session(), reopen=reopen)
    assert connection.reset(kind="pin").startswith("The reset took the debug connection")
    assert len(attempts) == 3


@pytest.mark.parametrize("operation", ["erase_chip", "erase_ranges"])
def test_the_target_is_reset_and_stopped_before_a_flash_routine_runs(monkeypatch, operation):
    """Reported on an XMC4500 attached to its running firmware: pyOCD stopped
    it amid the firmware, and the erase routine ended in a HardFault."""
    from pyocd.flash import eraser

    from pyflashgui.backends.pyocd_backend import PyocdConnection
    from pyflashgui.core.memory_map import FLASH, Region

    done = []

    class Target:
        def reset_and_halt(self, reset_type=None):
            done.append("reset and stopped")

    class Session:
        target = Target()

    class Eraser:
        class Mode:
            CHIP, SECTOR = "chip", "sector"

        def __init__(self, session, mode):
            pass

        def erase(self, ranges=None):
            done.append("erased")

    monkeypatch.setattr(eraser, "FlashEraser", Eraser)
    connection = PyocdConnection(Session())
    monkeypatch.setattr(
        connection, "regions", lambda: [Region("flash", 0x0800_0000, 0x1_0000, FLASH)]
    )
    if operation == "erase_chip":
        connection.erase_chip()
    else:
        connection.erase_ranges([(0x0800_0000, 0x1000)])
    assert done == ["reset and stopped", "erased"]
