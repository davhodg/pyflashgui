# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A J-Link, through SEGGER's own J-Link Commander.

Commander is the command line program that comes with SEGGER's J-Link
software. Driving it reaches every device that software knows -- far more
than Cortex-M -- at the price of needing a J-Link and SEGGER's software,
which the user installs and pyflashgui never carries.

It is run as a separate program, once for each thing asked of it, with a file
of commands to carry out. So there is no connection held open between one
operation and the next: connecting checks that the probe and the device
answer, and each operation after it attaches again by itself.

**Tried on one board so far**: listing the probe, connecting and reading
worked on an XMC4500 through its on-board J-Link. The rest is written from
SEGGER's documentation. How Commander's replies are read is the part most
likely to need putting right, and is kept in a few small functions for that
reason.

Commander says little while it works, so progress is the start and the end
and nothing between.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pyflashgui.backends.base import (
    ERASE_CHIP,
    ERASE_SECTORS,
    RESET_DEFAULT,
    Backend,
    BackendError,
    Cancelled,
    CancelledError,
    Connection,
    ProbeInfo,
    Progress,
    TargetInfo,
    Verification,
    _never,
    _nothing,
)
from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import FLASH, RAM, Region

#: What Commander is called: JLink.exe on Windows, JLinkExe elsewhere.
PROGRAM = "JLink.exe" if sys.platform == "win32" else "JLinkExe"

#: The debug interfaces offered, the first being the one used when none is
#: chosen. As Commander's ``-If`` takes them.
INTERFACES = ("SWD", "JTAG", "cJTAG", "FINE")

#: How long each kind of run may take, in seconds, before it is given up on.
#: Generous: a large image on a slow interface takes minutes, and a run cut
#: short part way through programming is worse than one waited for.
QUICK_S = 30
LIST_S = 120
WORK_S = 900

NOT_FOUND = (
    "J-Link Commander was not found. It comes with SEGGER's J-Link software: install that, "
    "or say where it is with Tools > Settings > J-Link Commander location."
)

#: Said by Commander when the probe is there and the device does not answer.
#: Looked for as well as its exit code, which has been seen to be 0 with it.
NO_TARGET = "Cannot connect to target"

#: A J-Link script that does nothing where SEGGER's software would set the
#: device up after connecting to it. On some parts that set-up writes to
#: the device -- an S32K3's RAM is filled, for its error correction -- and
#: a read made to see what a running program left there finds it gone.
NO_SETUP_SCRIPT = "int SetupTarget(void) {\n  return 0;\n}\n"

#: Where Commander is, when it has been said. None to go and look.
_chosen: list[str] | None = None


def set_commander(command: str | Sequence[str] | None) -> None:
    """Use this Commander, or go back to looking for one.

    A path, or a whole command line as a list -- which is how the tests stand
    a script in for it.
    """
    global _chosen
    if not command:
        _chosen = None
    elif isinstance(command, str):
        _chosen = [command]
    else:
        _chosen = list(command)


def _version(folder: Path) -> tuple[int, int, str]:
    """The version in a folder's name, for sorting: JLink_V812a is (8, 12, "a").

    A folder with none sorts first, as the one SEGGER's installer keeps up
    to date when it is told to replace what is there.
    """
    found = re.search(r"V(\d+)(\d\d)([a-z]?)", folder.name, re.I)
    if found is None:
        return (10**6, 0, "")
    return (int(found.group(1)), int(found.group(2)), found.group(3).lower())


def _installed() -> list[Path]:
    """The folders SEGGER's installer uses, newest version first."""
    if sys.platform == "win32":
        roots = [
            Path(os.environ.get(name, default)) / "SEGGER"
            for name, default in (
                ("ProgramFiles", r"C:\Program Files"),
                ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            )
        ]
    else:
        roots = [Path("/opt/SEGGER"), Path("/Applications/SEGGER")]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += [p for p in root.glob("JLink*") if p.is_dir()]
    return sorted(found, key=_version, reverse=True)


def find_commander() -> list[str] | None:
    """The command that starts Commander, or None if there is none to be found."""
    if _chosen is not None:
        return list(_chosen)
    # Where SEGGER installs it before anywhere on the PATH: Java's
    # development kit has a program of the same name, and on a machine with
    # both it is as likely to be the one the PATH finds.
    for folder in _installed():
        if (candidate := folder / PROGRAM).is_file():
            return [str(candidate)]
    if (on_path := shutil.which(PROGRAM)) is not None and _is_seggers(Path(on_path)):
        return [on_path]
    return None


def report() -> list[str]:
    """For Help > Diagnostics: the Commander used, how it was found, and every
    J-Link software folder there is, newest first."""
    found = find_commander()
    if found is None:
        lines = ["not found"]
    else:
        how = "chosen in Tools > Settings" if _chosen is not None else "found"
        lines = [f"{' '.join(found)} ({how})"]
    folders = _installed()
    lines += [f"installed: {folder}" for folder in folders] or ["no J-Link software folder found"]
    return lines


def _is_seggers(program: Path) -> bool:
    """Whether a program of Commander's name is Commander, and not Java's jlink.

    SEGGER's sits beside the library it is a front for; Java's does not.
    """
    folder = program.resolve().parent
    return any(folder.glob("JLink*.dll")) or any(folder.glob("libjlinkarm*"))


def _short(path: str) -> str:
    """Windows' short name for a path, which has no spaces in it. The path
    itself where there is none to be had."""
    if sys.platform != "win32":
        return path
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(1024)
        got = ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer))
        return buffer.value if 0 < got < len(buffer) else path
    except (AttributeError, OSError):
        return path


def _named(path: Path | str) -> str:
    """A path as a command in a command file can take it.

    Commander is not sure to take a space in one, quoted or not. So a path
    with a space in it, or a letter outside ASCII, is given by the short name
    Windows keeps for it; and it goes in quotes regardless, which a J-Link
    has been seen to accept.
    """
    text = str(path)
    if " " in text or not text.isascii():
        text = _short(text)
    return f'"{text}"'


def _why(output: str) -> str:
    """The lines of Commander's output that say what went wrong.

    Its output is a transcript of everything it did, most of which went
    well. The lines that name a failure are the ones worth showing; with
    none that look like one, the last few are the best there is.
    """
    lines = [
        line.strip()
        for line in output.splitlines()
        # Its own announcement that it is stopping says nothing about why.
        if line.strip() and "will now exit" not in line.lower()
    ]
    telling = [
        line
        for line in lines
        if re.search(r"error|fail|cannot|could not|unknown|not found|timeout", line, re.I)
    ]
    return " ".join((telling or lines)[-3:]) or "it said nothing about why"


def run(arguments: Sequence[str], commands: Sequence[str], timeout: float, doing: str) -> str:
    """Run Commander once with these commands, and give back what it printed.

    ``arguments`` go on its command line and ``commands`` in a file it is
    pointed at, with Exit added so that it always comes back.
    """
    commander = find_commander()
    if commander is None:
        raise BackendError(NOT_FOUND)
    with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
        script = Path(folder) / "commands.jlink"
        script.write_text("\n".join([*commands, "Exit"]) + "\n", encoding="utf-8")
        command = [*commander, "-NoGui", "1", *arguments, "-CommandFile", str(script)]
        try:
            done = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
                # No console of its own: pyflashgui has none, and Windows
                # would otherwise open one for every run.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise BackendError(NOT_FOUND) from exc
        except subprocess.TimeoutExpired as exc:
            raise BackendError(
                f"{doing} was given up on: J-Link Commander had not finished after "
                f"{timeout:.0f} seconds."
            ) from exc
        except OSError as exc:
            raise BackendError(f"{doing} failed: J-Link Commander would not start: {exc}") from exc
    output = (done.stdout or "") + (done.stderr or "")
    wanted_a_target = "-AutoConnect" in arguments
    if done.returncode != 0 or (wanted_a_target and NO_TARGET.lower() in output.lower()):
        raise BackendError(f"{doing} failed: {_why(output)}")
    return output


# --- reading what Commander says ---------------------------------------------------------
#: The line SEGGER's software ends a download with, saying how long each part
#: took: ``J-Link: Flash download: Total: 3.052s (Prepare: 0.071s, Compare:
#: 0.014s, Erase: 1.890s, Program & Verify: 1.029s, Restore: 0.046s)``. Older
#: versions say "Total time needed".
_DOWNLOAD = re.compile(
    r"Flash download:\s*Total(?: time needed)?:\s*([\d.]+)\s*s\s*\(([^)]*)\)", re.I
)
_PART = re.compile(r"([A-Za-z& ]+?):\s*([\d.]+)\s*s")
#: Said when the flash held the image already, and nothing was written.
_SKIPPED = re.compile(r"Flash download:\s*Skipped", re.I)


def download_text(output: str) -> str | None:
    """What J-Link said a download did, as a sentence: what it took to erase,
    and to program and check, which happen inside one command and cannot be
    shown as they go. None if it did not say."""
    if _SKIPPED.search(output) and not _DOWNLOAD.search(output):
        return "J-Link found the flash held this already, and wrote nothing."
    found = _DOWNLOAD.search(output)
    if found is None:
        return None
    parts = {name.strip().lower(): float(seconds) for name, seconds in _PART.findall(found[2])}
    said = []
    if "erase" in parts:
        said.append(f"erased in {parts['erase']:.1f} s")
    if "program & verify" in parts:
        said.append(f"programmed and checked in {parts['program & verify']:.1f} s")
    if not said:
        return None
    return f"J-Link {' and '.join(said)}, {float(found[1]):.1f} s in all."


#: One line of ShowEmuList for each J-Link:
#: ``J-Link[0]: Connection: USB, Serial number: 801012345, ProductName: J-Link PLUS``
_PROBE = re.compile(r"Serial number:\s*(\d+)(?:.*?ProductName:\s*([^,\r\n]+))?", re.I)

#: One line of the device list ExpDevList writes: the maker, the device and
#: its core, each in quotes, and then its memory in braces.
_DEVICE = re.compile(r'^\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,?(.*)$')
#: A stretch of memory inside the braces: where it starts and how long it is.
_AREA = re.compile(r"0x([0-9A-Fa-f]+)\s*,\s*0x([0-9A-Fa-f]+)")


def parse_probes(output: str) -> list[ProbeInfo]:
    """The J-Links that ShowEmuList named, each once."""
    probes: dict[str, ProbeInfo] = {}
    for found in _PROBE.finditer(output):
        serial, product = found.group(1), (found.group(2) or "J-Link").strip()
        probes.setdefault(serial, ProbeInfo(serial, product, vendor="SEGGER", product=product))
    return list(probes.values())


def _groups(text: str) -> list[str]:
    """The outermost ``{...}`` groups of a line, braces inside them included."""
    groups, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                groups.append(text[start : index + 1])
    return groups


def _areas(group: str) -> list[tuple[int, int]]:
    """The (start, length) of each stretch of memory in one group, empty ones left out."""
    pairs = [(int(start, 16), int(length, 16)) for start, length in _AREA.findall(group)]
    return [pair for pair in pairs if pair[1] > 0]


class Device:
    """One device Commander knows: who makes it, its core and its memory."""

    def __init__(
        self,
        maker: str,
        name: str,
        core: str,
        flash: list[tuple[int, int]],
        ram: list[tuple[int, int]],
    ) -> None:
        self.maker, self.name, self.core = maker, name, core
        self.flash, self.ram = flash, ram

    def regions(self) -> list[Region]:
        """Its memory as pyflashgui's regions, lowest address first.

        Numbered, since SEGGER's list gives the areas no names. Nothing is
        known of how the flash is divided into sectors, so that is left as
        not known rather than made up.
        """
        made = [
            Region(f"Flash {index}", start, length, FLASH)
            for index, (start, length) in enumerate(self.flash)
        ]
        made += [
            Region(f"RAM {index}", start, length, RAM)
            for index, (start, length) in enumerate(self.ram)
        ]
        return sorted(made, key=lambda region: region.start)


def parse_devices(text: str) -> list[Device]:
    """The devices in the list Commander writes out with ExpDevList.

    A line for each: three fields in quotes -- maker, device, core -- then a
    group in braces of its flash areas and another of its RAM areas, each
    area a start and a length in hexadecimal. A line that is not one of
    those, the line of headings among them, is passed over.
    """
    devices: dict[str, Device] = {}
    for line in text.splitlines():
        found = _DEVICE.match(line)
        if found is None:
            continue
        maker, name, core = (found.group(i).strip() for i in (1, 2, 3))
        if not name or name.lower() == "device":
            continue
        groups = _groups(found.group(4))
        flash = _areas(groups[0]) if groups else []
        ram = _areas(groups[1]) if len(groups) > 1 else []
        devices.setdefault(name.upper(), Device(maker, name, core, flash, ram))
    return sorted(devices.values(), key=lambda device: device.name.lower())


class JLinkConnection(Connection):
    """A probe and a device that have answered once, and how to reach them again."""

    def __init__(self, arguments: list[str], device: str, regions: list[Region]) -> None:
        self._arguments: list[str] | None = arguments
        self._device = device
        self._regions = regions

    def _run(
        self,
        commands: Sequence[str],
        timeout: float,
        doing: str,
        skip_setup: bool = False,
    ) -> str:
        if self._arguments is None:
            raise BackendError("This connection has been closed.")
        if not skip_setup:
            return run(self._arguments, commands, timeout, doing)
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            # Written afresh each time rather than kept anywhere: it is
            # three lines, and a file somebody could edit would be a
            # setting nobody knew they had.
            script = Path(folder) / "no_setup.JLinkScript"
            script.write_text(NO_SETUP_SCRIPT, encoding="ascii")
            arguments = [*self._arguments, "-JLinkScriptFile", str(script)]
            return run(arguments, commands, timeout, doing)

    def regions(self) -> list[Region]:
        return list(self._regions)

    def details(self) -> list[str]:
        if self._arguments is None:
            return ["closed"]
        return [f"device: {self._device}", f"Commander run with: {' '.join(self._arguments)}"]

    def erase_chip(self) -> None:
        self._run(["H", "Erase"], WORK_S, f"Erasing {self._device}")

    def erase_ranges(self, ranges: Sequence[tuple[int, int]]) -> None:
        # Erase takes the first and the last address, and erases every
        # sector that any of the range falls in.
        commands = ["H"] + [
            f"Erase 0x{start:08X} 0x{start + length - 1:08X}" for start, length in ranges
        ]
        self._run(commands, WORK_S, f"Erasing part of {self._device}")

    def program(
        self,
        segments: Sequence[Segment],
        erase: str = ERASE_SECTORS,
        progress: Progress = _nothing,
    ) -> str | None:
        if erase not in (ERASE_SECTORS, ERASE_CHIP):
            raise BackendError(f"There is no way of erasing called {erase!r}.")
        import bincopy

        image = bincopy.BinFile()
        for segment in segments:
            image.add_binary(segment.data, address=segment.address)
        progress(0.0)
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            # Handed over as one Intel HEX file whatever the files were:
            # the bytes are the ones pyflashgui read and showed in its
            # memory map, and Commander reads them once.
            path = Path(folder) / "image.hex"
            path.write_text(image.as_ihex(), encoding="ascii")
            # Stopped, and not restarted first: a device is programmed as it
            # is found, and restarting it is Reset's to do afterwards.
            commands = ["H"]
            if erase == ERASE_CHIP:
                commands.append("Erase")
            # LoadFile erases the sectors it writes to, and checks what it
            # wrote, by itself.
            commands.append(f"LoadFile {_named(path)}")
            said = self._run(commands, WORK_S, f"Programming {self._device}")
        progress(1.0)
        return download_text(said)

    def read(
        self, address: int, length: int, resume: bool = False, skip_setup: bool = False
    ) -> bytes:
        """Stopped while it is read, so that what is read is one moment's.

        ``resume`` sets the device going again afterwards, for a read that
        somebody asked for of a device that was running. ``skip_setup``
        leaves out SEGGER's own setting up of the device: see
        NO_SETUP_SCRIPT.
        """
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            path = Path(folder) / "read.bin"
            commands = ["H", f"SaveBin {_named(path)} 0x{address:X} 0x{length:X}"]
            if resume:
                commands.append("G")
            self._run(commands, WORK_S, f"Reading {length} bytes at {address:08X}", skip_setup)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise BackendError(
                    f"Reading {length} bytes at {address:08X} failed: J-Link Commander "
                    "wrote no file."
                ) from exc
        if len(data) != length:
            raise BackendError(
                f"Reading at {address:08X} gave {len(data)} bytes where {length} were asked for."
            )
        return data

    def read_range(
        self,
        address: int,
        length: int,
        progress: Progress = _nothing,
        cancelled: Cancelled = _never,
        skip_setup: bool = False,
    ) -> bytes:
        """All of it in one run of Commander, which is quicker than many."""
        if cancelled():
            raise CancelledError("Reading was cancelled.")
        progress(0.0)
        data = self.read(address, length, resume=True, skip_setup=skip_setup)
        progress(1.0)
        return data

    def verify(
        self,
        segments: Sequence[Segment],
        progress: Progress = _nothing,
        cancelled: Cancelled = _never,
    ) -> Verification:
        """Read each run of bytes back whole, and compare.

        The same comparison as every other backend's, a run at a time rather
        than a few kilobytes at a time: each read starts Commander afresh,
        and a thousand of those for one image would take the afternoon.
        """
        total = sum(len(s) for s in segments)
        checked = different = 0
        first: tuple[int, int, int] | None = None
        progress(0.0)
        for segment in segments:
            if cancelled():
                raise CancelledError("Verifying was cancelled.")
            found = self.read(segment.address, len(segment))
            if found != segment.data:
                for index, (want, have) in enumerate(zip(segment.data, found, strict=True)):
                    if want != have:
                        different += 1
                        if first is None:
                            first = (segment.address + index, want, have)
            checked += len(segment)
            progress(checked / total)
        return Verification(checked=checked, different=different, first=first)

    def write(self, address: int, data: bytes) -> None:
        """Stopped while it is written, and set going again, as a read is."""
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            path = Path(folder) / "write.bin"
            path.write_bytes(data)
            commands = ["H", f"LoadBin {_named(path)}, 0x{address:X}", "G"]
            self._run(commands, WORK_S, f"Writing {len(data)} bytes at {address:08X}")

    def reset(self, halt: bool = False, kind: str = RESET_DEFAULT) -> None:
        if kind != RESET_DEFAULT:
            raise BackendError("J-Link Commander resets each device its own way, and no other.")
        # R restarts the device and leaves it stopped; G sets it going.
        self._run(["R"] if halt else ["R", "G"], QUICK_S, f"Resetting {self._device}")

    def close(self) -> None:
        self._arguments = None


class JLinkBackend(Backend):
    # Commander's -speed auto: the J-Link finds the fastest that works.
    default_speed = "Default (auto)"
    name = "jlink"
    label = "J-Link Commander"
    interfaces = INTERFACES
    #: SEGGER's list says where a device's memory is, and not every address
    #: it can be reached by: flash that also appears at a second address is
    #: listed once. So a file outside the list may still be one it takes.
    map_is_complete = False
    can_skip_setup = True

    def __init__(self) -> None:
        #: The devices Commander knows, by name in capitals, once it has been
        #: asked: the list is thousands long and does not change while
        #: pyflashgui runs.
        self._devices: dict[str, Device] | None = None

    def probes(self) -> list[ProbeInfo]:
        # No -ExitOnError: with no J-Link plugged in Commander fails to open
        # one, and that is an empty list rather than a fault.
        output = run([], ["ShowEmuList USB"], QUICK_S, "Looking for J-Links")
        return parse_probes(output)

    def _known(self) -> dict[str, Device]:
        if self._devices is not None:
            return self._devices
        if find_commander() is None:
            # Said once, by the probes: the target can still be typed in.
            return {}
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            path = Path(folder) / "devices.csv"
            try:
                run([], [f"ExpDevList {_named(path)}"], LIST_S, "Listing the devices")
                # Not UTF-8: a maker's name has been seen with a letter in
                # it that is not, and latin-1 reads any byte there is.
                text = path.read_text(encoding="latin-1")
            except (BackendError, OSError):
                # A Commander that will not write the list still programs a
                # device whose name is typed in.
                text = ""
        self._devices = {device.name.upper(): device for device in parse_devices(text)}
        return self._devices

    def device(self, target: str) -> Device | None:
        """What is known of the device of this name, whatever its capitals."""
        return self._known().get(target.strip().upper())

    def targets(self) -> list[TargetInfo]:
        return [
            TargetInfo(device.name, vendor=device.maker, source="J-Link software", core=device.core)
            for device in self._known().values()
        ]

    def regions(self, target: str) -> list[Region]:
        device = self.device(target)
        return device.regions() if device is not None else []

    def connect(
        self,
        probe: str,
        target: str,
        frequency: int | None = None,
        interface: str | None = None,
        stop: bool = True,
    ) -> Connection:
        if not probe:
            raise BackendError("No J-Link is chosen.")
        if not target:
            raise BackendError("No device is chosen.")
        chosen = interface or INTERFACES[0]
        if chosen not in INTERFACES:
            raise BackendError(f"{chosen} is not an interface J-Link Commander is asked for here.")
        speed = "auto" if frequency is None else str(max(1, int(frequency) // 1000))
        arguments = [
            "-ExitOnError",
            "1",
            "-AutoConnect",
            "1",
            "-USB",
            probe,
            "-Device",
            target,
            "-If",
            chosen,
            "-Speed",
            speed,
        ]
        if chosen in ("JTAG", "cJTAG"):
            # Let it work out where the device sits in the scan chain.
            arguments += ["-JTAGConf", "-1,-1"]
        # Looked up first, while nothing is attached: it may mean asking
        # Commander for its list of devices, which is a run of its own.
        regions = self.regions(target)
        # With nothing to do but leave: a run that comes back clean has
        # opened the probe and found the device answering.
        run(arguments, [], QUICK_S, f"Connecting to {target}")
        connection = JLinkConnection(arguments, target, regions)
        connection.speed = "the speed J-Link chooses" if speed == "auto" else f"{speed} kHz"
        return connection
