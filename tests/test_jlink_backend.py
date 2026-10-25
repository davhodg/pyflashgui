# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The J-Link Commander backend, against a stand-in for Commander.

See ``commander_sim.py`` for what that does and does not show: that the right
things are asked for, in the order and form SEGGER's documentation gives, and
that the answers expected are coped with. Not that a real J-Link gives them.
"""

import json
import sys
from pathlib import Path

import pytest

from pyflashgui import backends
from pyflashgui.backends import jlink_backend
from pyflashgui.backends.base import ERASE_CHIP, BackendError, CancelledError
from pyflashgui.backends.jlink_backend import parse_devices, parse_probes
from pyflashgui.core.images import Segment

SIM = str(Path(__file__).with_name("commander_sim.py"))
SERIAL = "801012345"
DEVICE = "STM32F103ZE"
FLASH_AT = 0x0800_0000
RAM_AT = 0x2000_0000


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A folder for the stand-in's flash, and the stand-in in place of Commander."""
    monkeypatch.setenv("COMMANDER_SIM_HOME", str(tmp_path))
    jlink_backend.set_commander([sys.executable, SIM])
    yield tmp_path
    jlink_backend.set_commander(None)


@pytest.fixture
def backend(home):
    return backends.get("jlink")


@pytest.fixture
def connection(backend):
    with backend.connect(SERIAL, DEVICE, 4_000_000) as made:
        yield made


def runs(home) -> list[dict]:
    """Each time Commander was started: what it was given and told to do."""
    return json.loads((home / "runs.json").read_text())


# --- finding Commander ----------------------------------------------------------------
def test_with_no_commander_it_says_where_to_get_one(monkeypatch):
    jlink_backend.set_commander(None)
    monkeypatch.setattr(jlink_backend.shutil, "which", lambda _name: None)
    monkeypatch.setattr(jlink_backend, "_installed", lambda: [])
    backend = backends.get("jlink")
    with pytest.raises(BackendError, match="J-Link Commander was not found"):
        backend.probes()
    assert backend.targets() == [], "said once, and the target can still be typed in"
    with pytest.raises(BackendError, match="Tools > Settings"):
        backend.connect(SERIAL, DEVICE)


def test_commander_is_found_where_segger_installs_it(tmp_path, monkeypatch):
    jlink_backend.set_commander(None)
    monkeypatch.setattr(jlink_backend.shutil, "which", lambda _name: None)
    older, newer = tmp_path / "JLink_V798", tmp_path / "JLink_V812"
    for folder in (older, newer):
        folder.mkdir()
        (folder / jlink_backend.PROGRAM).write_text("")
    monkeypatch.setattr(jlink_backend, "_installed", lambda: [newer, older])
    assert jlink_backend.find_commander() == [str(newer / jlink_backend.PROGRAM)]
    monkeypatch.setattr(jlink_backend, "_installed", lambda: [])
    javas = tmp_path / "jdk" / jlink_backend.PROGRAM
    javas.parent.mkdir()
    javas.write_text("")
    monkeypatch.setattr(jlink_backend.shutil, "which", lambda _name: str(javas))
    assert jlink_backend.find_commander() is None, "Java has a jlink of its own"
    (javas.parent / "JLink_x64.dll").write_text("")
    assert jlink_backend.find_commander() == [str(javas)], "beside SEGGER's library, it is"
    jlink_backend.set_commander("D:/tools/JLink.exe")
    assert jlink_backend.find_commander() == ["D:/tools/JLink.exe"], "one that was chosen wins"
    jlink_backend.set_commander(None)


# --- what is there --------------------------------------------------------------------
def test_the_probes_are_the_j_links_commander_lists(backend, home, monkeypatch):
    monkeypatch.setenv("COMMANDER_SIM_PROBES", "801012345:J-Link PLUS,50123456:J-Link EDU Mini")
    found = backend.probes()
    assert [(p.unique_id, p.description) for p in found] == [
        ("801012345", "J-Link PLUS"),
        ("50123456", "J-Link EDU Mini"),
    ]
    assert runs(home)[-1]["commands"] == ["ShowEmuList USB", "Exit"]
    assert runs(home)[-1]["options"]["-nogui"] == "1"


def test_no_j_link_plugged_in_is_an_empty_list_and_not_a_fault(backend, monkeypatch):
    monkeypatch.setenv("COMMANDER_SIM_PROBES", "none")
    assert backend.probes() == []


def test_the_targets_are_the_devices_commander_knows_asked_for_once(backend, home):
    names = {t.name: t for t in backend.targets()}
    assert set(names) == {"STM32F103ZE", "S32K310", "AM2434_R5F0_0"}
    assert names["AM2434_R5F0_0"].vendor == "TI", "more than Cortex-M, which is the point"
    assert names["AM2434_R5F0_0"].core == "Cortex-R5"
    assert names["STM32F103ZE"].source == "J-Link software"
    backend.targets()
    assert sum("ExpDevList" in run["commands"][0] for run in runs(home)) == 1


def test_a_devices_memory_is_what_commanders_list_says(backend, connection):
    flash, ram = backend.regions(DEVICE)
    assert (flash.name, flash.start, flash.length, flash.kind) == (
        "Flash 0",
        0x0800_0000,
        0x8_0000,
        "flash",
    )
    assert (ram.name, ram.start, ram.length, ram.kind) == ("RAM 0", 0x2000_0000, 0x1_0000, "ram")
    assert flash.sector_size == 0, "how it is divided into sectors is not said, so not made up"
    assert connection.regions() == [flash, ram]
    assert backend.regions("stm32f103ze") == [flash, ram], "whatever its capitals"
    assert backend.regions("NOT_A_DEVICE") == []


def test_a_device_with_several_flashes_has_each_and_no_empty_ones(backend):
    """As a real part has them: code flash, data flash and a small one besides."""
    regions = backend.regions("S32K310")
    assert [(r.name, r.start, r.length) for r in regions] == [
        ("Flash 0", 0x0040_0000, 0x8_0000),
        ("Flash 1", 0x1000_0000, 0x1_0000),
        ("Flash 2", 0x1B00_0000, 0x380),
        ("RAM 0", 0x2000_0000, 0x8000),
    ]
    assert backend.regions("AM2434_R5F0_0")[0].kind == "ram", "a device with no flash listed"


def test_the_list_is_not_claimed_to_be_every_address_a_device_has(backend):
    """Flash that also appears at a second address is listed once."""
    from pyflashgui.core.images import BINARY, Image
    from pyflashgui.core.memory_map import lay_out

    assert backend.map_is_complete is False and backends.get("pyocd").map_is_complete is True
    elsewhere = Image("app.hex", BINARY, (Segment(0x0C00_0000, bytes(16)),))
    layout = lay_out([elsewhere], backend.regions(DEVICE), backend.map_is_complete)
    assert layout.programmable, "a warning, and Commander has the last word"
    assert layout.problems[0].level == "warning"
    assert "outside the memory listed for this target" in layout.problems[0].message


def test_the_interfaces_on_offer_are_commanders(backend):
    assert backend.interfaces[0] == "SWD" and "JTAG" in backend.interfaces
    assert backends.get("pyocd").interfaces == ()


# --- connecting -----------------------------------------------------------------------
def test_connecting_checks_that_the_probe_and_the_device_answer(backend, home):
    backend.connect(SERIAL, DEVICE, 4_000_000, "SWD").close()
    options = runs(home)[-1]["options"]
    assert options["-usb"] == SERIAL and options["-device"] == DEVICE
    assert options["-if"] == "SWD" and options["-speed"] == "4000"
    assert options["-autoconnect"] == "1" and options["-exitonerror"] == "1"
    assert "-jtagconf" not in options
    assert runs(home)[-1]["commands"] == ["Exit"]


def test_the_probes_own_speed_and_jtag_are_asked_for_as_commander_takes_them(backend, home):
    backend.connect(SERIAL, DEVICE, None, "JTAG").close()
    options = runs(home)[-1]["options"]
    assert options["-speed"] == "auto" and options["-if"] == "JTAG"
    assert options["-jtagconf"] == "-1,-1"


def test_a_connect_that_fails_says_what_commander_said(backend, monkeypatch):
    with pytest.raises(BackendError, match="Unknown device 'NOSUCH' selected"):
        backend.connect(SERIAL, "NOSUCH")
    with pytest.raises(BackendError, match="Cannot connect to J-Link"):
        backend.connect("11111111", DEVICE)
    monkeypatch.setenv("COMMANDER_SIM_NO_TARGET", "1")
    with pytest.raises(BackendError, match=r"Connecting to STM32F103ZE failed: .*target"):
        backend.connect(SERIAL, DEVICE)
    with pytest.raises(BackendError, match="not an interface"):
        backend.connect(SERIAL, DEVICE, interface="SPI")


def test_a_closed_connection_refuses(backend):
    connection = backend.connect(SERIAL, DEVICE)
    connection.close()
    with pytest.raises(BackendError, match="closed"):
        connection.reset()


# --- programming ----------------------------------------------------------------------
def test_programming_hands_commander_one_hex_file_of_the_bytes_read(connection, home):
    segments = [Segment(FLASH_AT, b"boot" * 8), Segment(FLASH_AT + 0x4000, b"application")]
    seen = []
    connection.program(segments, progress=seen.append)
    commands = runs(home)[-1]["commands"]
    assert commands[0] == "H", "stopped, and not restarted: it is programmed as it is found"
    assert commands[1].startswith('LoadFile "') and commands[1].endswith('image.hex"')
    assert commands[-1] == "Exit"
    assert seen == [0.0, 1.0], "the start and the end, which is all Commander gives"
    assert connection.read(FLASH_AT, 32) == b"boot" * 8
    assert connection.read(FLASH_AT + 0x4000, 11) == b"application"


def test_erasing_everything_first_is_an_erase_before_the_load(connection, home):
    connection.program([Segment(FLASH_AT + 0x8000, b"old!")])
    connection.program([Segment(FLASH_AT, b"new!")], erase=ERASE_CHIP)
    assert [c.split()[0] for c in runs(home)[-1]["commands"]] == [
        "H",
        "Erase",
        "LoadFile",
        "Exit",
    ]
    assert connection.read(FLASH_AT + 0x8000, 4) == b"\xff" * 4


def test_a_path_with_a_space_in_it_reaches_commander_whole(connection, home, monkeypatch):
    spaced = home / "a folder"
    spaced.mkdir()
    monkeypatch.setattr(jlink_backend.tempfile, "tempdir", str(spaced))
    connection.program([Segment(FLASH_AT, b"abcd")])
    assert connection.read(FLASH_AT, 4) == b"abcd"


def test_reading_asks_for_the_bytes_and_checks_it_got_them(connection, home):
    connection.program([Segment(FLASH_AT, b"abcdefgh")])
    assert connection.read(FLASH_AT + 2, 4) == b"cdef"
    halt, command, leave = runs(home)[-1]["commands"]
    assert (halt, leave) == ("H", "Exit"), "stopped while it is read, and left stopped"
    assert command.startswith('SaveBin "') and command.endswith(" 0x8000002 0x4")
    connection.read_range(FLASH_AT, 8)
    assert runs(home)[-1]["commands"][-2:] == ["G", "Exit"], "a read asked for sets it going again"


def test_writing_hands_commander_the_bytes_and_sets_the_device_going(connection, home):
    connection.write(RAM_AT, b"wxyz")
    halt, command, go, leave = runs(home)[-1]["commands"]
    assert (halt, go, leave) == ("H", "G", "Exit")
    assert command.startswith('LoadBin "') and command.endswith(f'write.bin", 0x{RAM_AT:X}')
    assert connection.read(RAM_AT, 4) == b"wxyz"


def test_verifying_reads_each_run_back_once_and_compares(connection, home):
    segments = [Segment(FLASH_AT, bytes(range(200)) * 100), Segment(FLASH_AT + 0x8000, b"tail")]
    connection.program(segments)
    before = len(runs(home))
    seen = []
    result = connection.verify(segments, progress=seen.append)
    assert result.ok and result.checked == 20004
    assert len(runs(home)) - before == 2, "one start of Commander for each run of bytes"
    assert seen[0] == 0.0 and seen[-1] == 1.0


def test_a_byte_that_did_not_take_is_found(connection, monkeypatch):
    monkeypatch.setenv("COMMANDER_SIM_SPOIL", hex(FLASH_AT + 5))
    data = bytes(range(16))
    connection.program([Segment(FLASH_AT, data)])
    result = connection.verify([Segment(FLASH_AT, data)])
    assert not result.ok and result.different == 1
    assert result.first == (FLASH_AT + 5, 5, 5 ^ 0xFF)


def test_verifying_stops_between_runs_when_asked(connection):
    segments = [Segment(FLASH_AT, b"one"), Segment(FLASH_AT + 0x1000, b"two")]
    connection.program(segments)
    with pytest.raises(CancelledError):
        connection.verify(segments, cancelled=lambda: True)


def test_erase_and_reset(connection, home):
    connection.program([Segment(FLASH_AT, b"abcd")])
    connection.erase_chip()
    assert runs(home)[-1]["commands"] == ["H", "Erase", "Exit"]
    assert connection.read(FLASH_AT, 4) == b"\xff" * 4
    connection.reset()
    assert runs(home)[-1]["commands"] == ["R", "G", "Exit"]
    connection.reset(halt=True)
    assert runs(home)[-1]["commands"] == ["R", "Exit"]


def test_a_commander_that_never_comes_back_is_given_up_on(backend, monkeypatch):
    import subprocess

    def hang(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(jlink_backend.subprocess, "run", hang)
    with pytest.raises(BackendError, match="had not finished after 30 seconds"):
        backend.probes()


# --- reading what Commander says ------------------------------------------------------
def test_probes_are_read_from_the_lines_that_name_one():
    said = (
        "SEGGER J-Link Commander V8.12\n"
        "J-Link[0]: Connection: USB, Serial number: 801012345, ProductName: J-Link PLUS\n"
        "J-Link[1]: Connection: USB, Serial number: 50123456, ProductName: J-Link EDU Mini\n"
        "J-Link>\n"
    )
    assert [(p.unique_id, p.product) for p in parse_probes(said)] == [
        ("801012345", "J-Link PLUS"),
        ("50123456", "J-Link EDU Mini"),
    ]
    assert parse_probes("Serial number: 123\nSerial number: 123\n")[0].description == "J-Link"
    assert parse_probes("Connecting to J-Link via USB...FAILED") == []


def test_devices_are_read_with_their_core_and_their_memory():
    listed = (
        '"Manufacturer", "Device", "Core", "Flash areas", "RAM areas"\n'
        '"ST", "STM32F103ZE", "Cortex-M3", {{0x08000000, 0x00080000}}, {{0x20000000, 0x00010000}}\n'
        '"NXP", "S32K310", "Cortex-M7", {{0x00400000, 0x80000}, {0x10000000, 0x10000}}, '
        "{{0x20000000, 0x8000}, {0x0, 0x0}}\n"
        '"TI", "AM2434_R5F0_0", "Cortex-R5"\n'
        '"ST", "stm32f103ze", "Cortex-M3", {{0x0, 0x10}}, {}\n'
        "\n"
        "not a row\n"
    )
    devices = {d.name: d for d in parse_devices(listed)}
    assert list(devices) == ["AM2434_R5F0_0", "S32K310", "STM32F103ZE"], "each once, by name"
    assert (devices["S32K310"].maker, devices["S32K310"].core) == ("NXP", "Cortex-M7")
    assert devices["S32K310"].flash == [(0x0040_0000, 0x8_0000), (0x1000_0000, 0x1_0000)]
    assert devices["S32K310"].ram == [(0x2000_0000, 0x8000)], "an area of no length is not one"
    assert devices["AM2434_R5F0_0"].flash == [] and devices["AM2434_R5F0_0"].ram == []
    assert devices["STM32F103ZE"].flash == [(0x0800_0000, 0x8_0000)], "the first of a name wins"
    assert parse_devices("") == []


# --- through the window ---------------------------------------------------------------
def test_the_bar_offers_an_interface_only_where_it_can_be_chosen(app, home, monkeypatch):
    import time

    from PySide6.QtCore import QCoreApplication, QSettings

    from pyflashgui.core import workspaces
    from pyflashgui.core.settings import Settings
    from pyflashgui.ui import probe_bar
    from pyflashgui.ui.main_window import COMMANDER_SETTING, MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(home / "pyflashgui"))
    QSettings().clear()
    # As Tools > Settings would have left it. The window reads it as it
    # starts, so the stand-in has to be what it finds there.
    QSettings().setValue(COMMANDER_SETTING, SIM)
    monkeypatch.setattr(
        jlink_backend, "set_commander", lambda _path: None
    )  # the list set by the fixture stays
    Settings(workspaces.settings_path()).set(probe_bar.BACKEND_KEY, "jlink")
    window = MainWindow()
    window.show()
    bar = window.probe_bar
    try:
        deadline = time.monotonic() + 20
        while not (bar.chosen_probe() == SERIAL and bar.target.count() == 3):
            assert time.monotonic() < deadline, "the probes and devices never arrived"
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert bar._interface_action.isVisible()
        assert [bar.interface.itemText(i) for i in range(bar.interface.count())] == list(
            jlink_backend.INTERFACES
        )
        bar.backend.setCurrentIndex(bar.backend.findData("simulated"))
        assert not bar._interface_action.isVisible() and bar.chosen_interface() is None
    finally:
        window.close()


def test_what_went_wrong_is_the_line_that_says_so_and_not_the_one_that_says_goodbye():
    """As a J-Link said it, reading an address the XMC4500 does not have."""
    said = (
        "Connecting to target via SWD\n"
        "Cortex-M4 identified.\n"
        "J-Link Commander will now exit on Error\n"
        "Reading 1048576 bytes from addr 0x00C00000 into file...Could not read memory.\n"
    )
    assert jlink_backend._why(said) == (
        "Reading 1048576 bytes from addr 0x00C00000 into file...Could not read memory."
    )


# --- erasing part of it ---------------------------------------------------------------
def test_erasing_a_range_gives_commander_its_first_and_last_address(connection, home):
    connection.program([Segment(FLASH_AT, bytes(0x3000))])
    connection.erase_ranges([(FLASH_AT + 0x1000, 0x1000), (FLASH_AT + 0x2800, 0x10)])
    assert runs(home)[-1]["commands"] == [
        "H",
        "Erase 0x08001000 0x08001FFF",
        "Erase 0x08002800 0x0800280F",
        "Exit",
    ]
    assert connection.read(FLASH_AT, 0x1000) == bytes(0x1000), "what was not asked for is kept"
    assert connection.read(FLASH_AT + 0x1000, 0x2000) == b"\xff" * 0x2000


# --- the things a real J-Link has taught ----------------------------------------------
def test_a_device_that_does_not_answer_is_a_failure_whatever_the_exit_code(backend, monkeypatch):
    """Commander can say so with an exit code of 0."""
    import subprocess

    def answers_and_leaves(command, **_kwargs):
        said = "Connecting to target via SWD\nCannot connect to target.\n"
        return subprocess.CompletedProcess(command, 0, stdout=said, stderr="")

    monkeypatch.setattr(jlink_backend.subprocess, "run", answers_and_leaves)
    monkeypatch.setattr(backend, "regions", lambda _target: [])
    with pytest.raises(BackendError, match="Cannot connect to target"):
        backend.connect(SERIAL, DEVICE)


def test_a_path_commander_might_not_take_is_given_by_its_short_name(tmp_path, monkeypatch):
    monkeypatch.setattr(jlink_backend, "_short", lambda path: "C:/SHORT~1/IMAGE.HEX")
    assert jlink_backend._named("C:/plain/image.hex") == '"C:/plain/image.hex"'
    assert jlink_backend._named("C:/a folder/image.hex") == '"C:/SHORT~1/IMAGE.HEX"'
    assert jlink_backend._named("C:/caf\u00e9/image.hex") == '"C:/SHORT~1/IMAGE.HEX"'


def test_the_newest_commander_installed_is_the_one_used(tmp_path):
    for name in ("JLink_V798a", "JLink_V812", "JLink_V810b", "JLink"):
        (tmp_path / name).mkdir()
    ordered = sorted(tmp_path.iterdir(), key=jlink_backend._version, reverse=True)
    assert [p.name for p in ordered] == ["JLink", "JLink_V812", "JLink_V810b", "JLink_V798a"]


# --- reading without setting the device up --------------------------------------------
def test_a_read_can_leave_out_seggers_setting_up_of_the_device(connection, home):
    """For a part where that set-up fills the RAM a running program was using."""
    connection.program([Segment(FLASH_AT, b"abcd")])
    assert connection.read_range(FLASH_AT, 4, skip_setup=True) == b"abcd"
    options = runs(home)[-1]["options"]
    assert options["-jlinkscriptfile"].endswith("no_setup.JLinkScript")
    assert options["script"] == "int SetupTarget(void) {\n  return 0;\n}\n"
    assert options["-device"] == DEVICE, "and still the same probe, device and interface"
    assert not Path(options["-jlinkscriptfile"]).exists(), "written for the run, and gone after"


def test_nothing_but_a_read_asked_for_that_way_leaves_it_out(connection, home):
    connection.program([Segment(FLASH_AT, b"abcd")])
    connection.read_range(FLASH_AT, 4)
    connection.verify([Segment(FLASH_AT, b"abcd")])
    connection.erase_ranges([(FLASH_AT, 4)])
    connection.erase_chip()
    connection.reset()
    assert not any("-jlinkscriptfile" in run["options"] for run in runs(home))
    assert backends.get("jlink").can_skip_setup and not backends.get("pyocd").can_skip_setup


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        (
            "J-Link: Flash download: Total: 3.052s (Prepare: 0.071s, Compare: 0.014s, "
            "Erase: 1.890s, Program & Verify: 1.029s, Restore: 0.046s)",
            "J-Link erased in 1.9 s and programmed and checked in 1.0 s, 3.1 s in all.",
        ),
        (
            "J-Link: Flash download: Total time needed: 13.580s (Prepare: 0.082s, Compare: "
            "0.000s, Erase: 7.693s, Program & Verify: 5.739s, Restore: 0.064s)",
            "J-Link erased in 7.7 s and programmed and checked in 5.7 s, 13.6 s in all.",
        ),
        (
            "J-Link: Flash download: Skipped. Contents already match",
            "J-Link found the flash held this already, and wrote nothing.",
        ),
        ("O.K.", None),
    ],
)
def test_what_a_download_did_is_said_from_what_j_link_printed(said, expected):
    """Asked for: LoadFile erases, programs and checks in one command, with
    nothing to show while it does; afterwards it says how long each took."""
    from pyflashgui.backends.jlink_backend import download_text

    assert download_text(f"Downloading file...\n{said}\nO.K.\n") == expected
