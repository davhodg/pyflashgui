# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The flasher: backend calls off the GUI thread, and what comes back said in words."""

import time

import pytest
from PySide6.QtCore import QCoreApplication

from pyflashgui import backends
from pyflashgui.backends.base import ERASE_CHIP, VERIFY_CHUNK
from pyflashgui.core.events import ERROR, GOOD, WARNING, EventLog
from pyflashgui.core.flasher import Flasher, size_text, verification_text
from pyflashgui.core.images import BINARY, Image, Segment

PROBE = "SIM0001"
TARGET = "sim_single"
FLASH_AT = 0x0800_0000


def wait_for(condition, timeout: float = 5.0) -> None:
    """Run the event loop until this is true, which is how results arrive."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("it did not happen in time")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def image(name: str, address: int, data: bytes) -> Image:
    return Image(name, BINARY, (Segment(address, data),))


class Said:
    """Everything posted to the Event Log, with its level."""

    def __init__(self, events: EventLog) -> None:
        self.lines: list[tuple[str, str]] = []
        events.posted.connect(lambda message, level: self.lines.append((level, message)))

    def at(self, level: str) -> list[str]:
        return [message for said, message in self.lines if said == level]


@pytest.fixture
def events(app):
    return EventLog()


@pytest.fixture
def said(events):
    return Said(events)


@pytest.fixture
def flasher(events):
    made = Flasher(events, backend="simulated")
    yield made
    made.shutdown()


@pytest.fixture
def connected(flasher):
    flasher.connect_to(PROBE, TARGET)
    wait_for(lambda: flasher.connected)
    return flasher


def finish(flasher) -> list[tuple[str, bool]]:
    """Wait for whatever is running, and say how each thing ended."""
    ended = []
    flasher.finished.connect(lambda name, ok: ended.append((name, ok)))
    wait_for(lambda: not flasher.busy)
    QCoreApplication.processEvents()
    return ended


# --- what is there --------------------------------------------------------------------
def test_probes_and_targets_arrive_as_signals(flasher):
    probes, targets = [], []
    flasher.probes_changed.connect(probes.extend)
    flasher.targets_changed.connect(targets.extend)
    flasher.refresh_probes()
    flasher.refresh_targets()
    wait_for(lambda: probes and targets)
    assert [p.unique_id for p in probes] == ["SIM0001", "SIM0002"]
    assert TARGET in {t.name for t in targets}
    assert not flasher.busy, "looking things up is not being busy with a target"


def test_a_targets_memory_is_known_before_it_is_connected_to(flasher):
    changed = []
    flasher.regions_changed.connect(lambda: changed.append(1))
    flasher.set_target(TARGET)
    wait_for(lambda: changed)
    assert [r.name for r in flasher.regions] == ["flash", "ram"]
    assert not flasher.connected


# --- connecting -----------------------------------------------------------------------
def test_connecting_says_so_and_knows_the_memory(said, connected):
    assert connected.target == TARGET and connected.probe == PROBE
    assert [r.name for r in connected.regions] == ["flash", "ram"]
    assert said.at(GOOD) == [f"Connected to {TARGET} through probe {PROBE}."]


def test_a_connect_that_fails_is_an_error_in_the_backends_own_words(flasher, said):
    flasher.connect_to("NOPE", TARGET)
    ended = finish(flasher)
    assert not flasher.connected
    assert said.at(ERROR) == ["There is no probe with the id NOPE."]
    assert ended == [("Connecting to sim_single", False)]


def test_disconnecting_lets_go_of_the_probe(connected, said):
    states = []
    connected.connection_changed.connect(states.append)
    connected.disconnect()
    assert states == [False] and not connected.connected
    wait_for(lambda: any("Disconnected" in line for _l, line in said.lines))
    connected.connect_to(PROBE, TARGET)  # which it could not, had it not been let go
    wait_for(lambda: connected.connected)


def test_nothing_is_done_to_a_target_that_is_not_connected(flasher, said):
    flasher.program([image("a.bin", FLASH_AT, b"\x01")])
    flasher.erase()
    flasher.reset()
    assert not flasher.busy
    assert len(said.at(WARNING)) == 3
    assert "needs a probe connected" in said.at(WARNING)[0]


# --- programming ----------------------------------------------------------------------
def test_programming_writes_verifies_resets_and_says_so(connected, said):
    data = bytes(range(200)) * 50
    steps = []
    connected.progress.connect(lambda label, fraction: steps.append((label, fraction)))
    connected.program([image("app.bin", FLASH_AT, data)])
    assert connected.busy
    ended = finish(connected)

    board = backends.get("simulated").board(PROBE)
    assert bytes(board.memory["flash"][: len(data)]) == data
    assert board.resets == 1
    assert ended == [("Programming", True)]
    assert said.at(GOOD)[-1].startswith(
        "Programmed 1 file, 9.8 KiB, verified, and reset the target"
    )
    labels = [label for label, _f in steps]
    assert "Programming" in labels and "Verifying" in labels
    assert labels.index("Programming") < labels.index("Verifying")
    assert ("Verifying", 1.0) in steps


def test_what_was_not_asked_for_is_not_done(connected, said):
    connected.program([image("app.bin", FLASH_AT, b"abcd")], verify=False, reset=False)
    finish(connected)
    assert backends.get("simulated").board(PROBE).resets == 0
    assert said.at(GOOD)[-1].startswith("Programmed 1 file, 4 bytes, in ")


def test_erasing_everything_first_is_passed_on(connected):
    connected.program([image("old.bin", FLASH_AT + 0x8000, b"old!")], verify=False, reset=False)
    finish(connected)
    connected.program([image("new.bin", FLASH_AT, b"new!")], erase=ERASE_CHIP, reset=False)
    finish(connected)
    flash = backends.get("simulated").board(PROBE).memory["flash"]
    assert bytes(flash[0x8000:0x8004]) == b"\xff" * 4


def test_a_file_the_target_has_no_room_for_is_an_error_and_not_a_crash(connected, said):
    connected.program([image("far.bin", 0x4000_0000, b"\x00")])
    ended = finish(connected)
    assert ended == [("Programming", False)]
    assert said.at(ERROR) == ["The target has no memory at 40000000."]
    assert not connected.busy and connected.connected, "and it can be tried again"


def test_a_verify_that_fails_says_where_and_does_not_reset(connected, said, monkeypatch):
    """What is in the flash is not what was meant to be: starting it helps nobody."""
    board = backends.get("simulated").board(PROBE)
    real = type(connected.connection).program

    def spoiled(self, segments, **kwargs):
        real(self, segments, **kwargs)
        board.memory["flash"][3] ^= 0xFF

    monkeypatch.setattr(type(connected.connection), "program", spoiled)
    connected.program([image("app.bin", FLASH_AT, b"\x10\x20\x30\x40\x50")])
    ended = finish(connected)
    assert ended == [("Programming", False)]
    assert board.resets == 0
    (line,) = said.at(ERROR)
    assert "the target does not hold what was sent" in line
    assert "1 byte differs of 5. The first is at 08000003" in line
    assert "the file has 40 and the target has BF" in line


def test_nothing_ticked_is_said_rather_than_sent(connected, said):
    connected.program([])
    connected.verify([])
    assert not connected.busy
    assert [line[:28] for line in said.at(WARNING)] == [
        "There is nothing to program:",
        "There is nothing to verify: ",
    ]


def test_one_thing_at_a_time(connected, said):
    connected.program([image("app.bin", FLASH_AT, bytes(VERIFY_CHUNK * 8))])
    connected.erase()  # while the first is still going
    finish(connected)
    assert "Erasing was not started: something else is still running." in said.at(WARNING)
    flash = backends.get("simulated").board(PROBE).memory["flash"]
    assert bytes(flash[:8]) == bytes(8), "so what was programmed is still there"


# --- verify, erase, reset -------------------------------------------------------------
def test_verify_alone_compares_and_changes_nothing(connected, said):
    connected.program([image("app.bin", FLASH_AT, b"abcd")], verify=False, reset=False)
    finish(connected)
    connected.verify([image("app.bin", FLASH_AT, b"abcd")])
    assert finish(connected) == [("Verifying", True)]
    assert said.at(GOOD)[-1] == "Verified: 4 bytes match the files."

    connected.verify([image("other.bin", FLASH_AT, b"abXd")])
    assert finish(connected) == [("Verifying", False)]
    assert "1 byte differs of 4" in said.at(ERROR)[-1]


def test_a_cancelled_verify_is_a_warning_and_not_a_failure_of_the_target(
    connected, said, monkeypatch
):
    data = bytes(VERIFY_CHUNK * 3)
    connected.program([image("app.bin", FLASH_AT, data)], verify=False, reset=False)
    finish(connected)
    real = type(connected.connection).read

    def read_then_cancel(self, address, length):
        connected.cancel()  # as somebody pressing Cancel part way through would
        return real(self, address, length)

    monkeypatch.setattr(type(connected.connection), "read", read_then_cancel)
    connected.verify([image("app.bin", FLASH_AT, data)])
    assert finish(connected) == [("Verifying", False)]
    assert said.at(WARNING)[-1] == "Verifying was cancelled."
    assert not said.at(ERROR)


def test_erase_and_reset(connected, said):
    connected.program([image("app.bin", FLASH_AT, b"abcd")], verify=False, reset=False)
    finish(connected)
    connected.erase()
    assert finish(connected) == [("Erasing", True)]
    board = backends.get("simulated").board(PROBE)
    assert bytes(board.memory["flash"][:4]) == b"\xff" * 4
    assert said.at(GOOD)[-1].startswith("Erased all of the flash of sim_single in ")
    connected.reset()
    assert finish(connected) == [("Resetting", True)]
    assert board.resets == 1


# --- changing backend -----------------------------------------------------------------
def test_changing_backend_lets_go_of_what_was_connected(connected):
    targets = []
    connected.targets_changed.connect(targets.extend)
    connected.set_backend("pyocd")
    assert not connected.connected and connected.backend.name == "pyocd"
    assert connected.regions == []
    wait_for(lambda: targets, timeout=30)
    assert "rp2350" in {t.name for t in targets}


# --- the words ------------------------------------------------------------------------
def test_sizes_are_said_as_somebody_would_say_them():
    assert [size_text(n) for n in (0, 1, 1023, 1024, 1536, 1024 * 1024, 5 * 1024 * 1024 // 2)] == [
        "0 bytes",
        "1 byte",
        "1023 bytes",
        "1.0 KiB",
        "1.5 KiB",
        "1.0 MiB",
        "2.5 MiB",
    ]


def test_a_verification_is_a_sentence():
    from pyflashgui.backends.base import Verification

    assert verification_text(Verification(2048, 0)) == "Verified: 2.0 KiB match the files."
    assert verification_text(Verification(100, 3, (0x0800_0010, 0xAB, 0x00))) == (
        "Verify failed: 3 bytes differ of 100. The first is at 08000010, "
        "where the file has AB and the target has 00."
    )
