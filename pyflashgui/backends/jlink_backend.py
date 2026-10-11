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

**Written from SEGGER's documentation and not yet tried on a J-Link.** What
Commander is asked to do is as its manual gives it; how its replies are read
is the part most likely to need putting right against the real thing, and is
kept in a few small functions for that reason.

Commander says little while it works, so progress is the start and the end
and nothing between.
"""

from __future__ import annotations

import csv
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
from pyflashgui.core.memory_map import Region

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
            # "JLink" for the current one, "JLink_V812" for each kept beside it.
            found += sorted((p for p in root.glob("JLink*") if p.is_dir()), reverse=True)
    return found


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


def _is_seggers(program: Path) -> bool:
    """Whether a program of Commander's name is Commander, and not Java's jlink.

    SEGGER's sits beside the library it is a front for; Java's does not.
    """
    folder = program.resolve().parent
    return any(folder.glob("JLink*.dll")) or any(folder.glob("libjlinkarm*"))


def _quoted(path: Path | str) -> str:
    """A path as a command file takes one: in quotes, for the spaces in it."""
    return f'"{path}"'


def _why(output: str) -> str:
    """The lines of Commander's output that say what went wrong.

    Its output is a transcript of everything it did, most of which went
    well. The lines that name a failure are the ones worth showing; with
    none that look like one, the last few are the best there is.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
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
    if done.returncode != 0:
        raise BackendError(f"{doing} failed: {_why(output)}")
    return output


# --- reading what Commander says ---------------------------------------------------------
#: One line of ShowEmuList for each J-Link:
#: ``J-Link[0]: Connection: USB, Serial number: 801012345, ProductName: J-Link PLUS``
_PROBE = re.compile(r"Serial number:\s*(\d+)(?:.*?ProductName:\s*([^,\r\n]+))?", re.I)


def parse_probes(output: str) -> list[ProbeInfo]:
    """The J-Links that ShowEmuList named, each once."""
    probes: dict[str, ProbeInfo] = {}
    for found in _PROBE.finditer(output):
        serial, product = found.group(1), (found.group(2) or "J-Link").strip()
        probes.setdefault(serial, ProbeInfo(serial, product, vendor="SEGGER", product=product))
    return list(probes.values())


def parse_devices(text: str) -> list[TargetInfo]:
    """The devices in the list Commander writes out with ExpDevList.

    A line for each, its first two fields the maker and the device's name in
    quotes. The fields after them describe its memory, in a form that has
    not been checked against the real thing, and are left alone: a memory map
    read wrongly would refuse files that are perfectly good.
    """
    devices: dict[str, TargetInfo] = {}
    for row in csv.reader(text.splitlines(), skipinitialspace=True):
        if len(row) < 2:
            continue
        maker, name = row[0].strip(), row[1].strip()
        if not name or name.lower() == "device":
            continue  # a blank line, or the line of headings
        devices.setdefault(name, TargetInfo(name, vendor=maker, source="J-Link software"))
    return sorted(devices.values(), key=lambda device: device.name.lower())


class JLinkConnection(Connection):
    """A probe and a device that have answered once, and how to reach them again."""

    def __init__(self, arguments: list[str], device: str) -> None:
        self._arguments: list[str] | None = arguments
        self._device = device

    def _run(self, commands: Sequence[str], timeout: float, doing: str) -> str:
        if self._arguments is None:
            raise BackendError("This connection has been closed.")
        return run(self._arguments, commands, timeout, doing)

    def regions(self) -> list[Region]:
        # Commander knows the device's memory and has no way of being asked
        # for it that has been checked here, so the map says it could not.
        return []

    def erase_chip(self) -> None:
        self._run(["Erase"], WORK_S, f"Erasing {self._device}")

    def program(
        self,
        segments: Sequence[Segment],
        erase: str = ERASE_SECTORS,
        progress: Progress = _nothing,
    ) -> None:
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
            commands = ["R", "H"]
            if erase == ERASE_CHIP:
                commands.append("Erase")
            # LoadFile erases the sectors it writes to, and checks what it
            # wrote, by itself.
            commands.append(f"LoadFile {_quoted(path)}")
            self._run(commands, WORK_S, f"Programming {self._device}")
        progress(1.0)

    def read(self, address: int, length: int) -> bytes:
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            path = Path(folder) / "read.bin"
            self._run(
                [f"SaveBin {_quoted(path)} 0x{address:X} 0x{length:X}"],
                WORK_S,
                f"Reading {length} bytes at {address:08X}",
            )
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

    def reset(self, halt: bool = False) -> None:
        # R restarts the device and leaves it stopped; G sets it going.
        self._run(["R"] if halt else ["R", "G"], QUICK_S, f"Resetting {self._device}")

    def close(self) -> None:
        self._arguments = None


class JLinkBackend(Backend):
    name = "jlink"
    label = "J-Link Commander"
    interfaces = INTERFACES

    def __init__(self) -> None:
        #: The devices Commander knows, once it has been asked: the list is
        #: thousands long and does not change while pyflashgui runs.
        self._devices: list[TargetInfo] | None = None

    def probes(self) -> list[ProbeInfo]:
        # No -ExitOnError: with no J-Link plugged in Commander fails to open
        # one, and that is an empty list rather than a fault.
        output = run([], ["ShowEmuList USB"], QUICK_S, "Looking for J-Links")
        return parse_probes(output)

    def targets(self) -> list[TargetInfo]:
        if self._devices is not None:
            return list(self._devices)
        if find_commander() is None:
            # Said once, by the probes: the target can still be typed in.
            return []
        with tempfile.TemporaryDirectory(prefix="pyflashgui-jlink-") as folder:
            path = Path(folder) / "devices.csv"
            try:
                run([], [f"ExpDevList {_quoted(path)}"], LIST_S, "Listing the devices")
                text = path.read_text(encoding="utf-8", errors="replace")
            except (BackendError, OSError):
                # A Commander that will not write the list still programs a
                # device whose name is typed in.
                text = ""
        self._devices = parse_devices(text)
        return list(self._devices)

    def regions(self, target: str) -> list[Region]:
        return []

    def connect(
        self,
        probe: str,
        target: str,
        frequency: int | None = None,
        interface: str | None = None,
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
        # With nothing to do but leave: a run that comes back clean has
        # opened the probe and found the device answering.
        run(arguments, [], QUICK_S, f"Connecting to {target}")
        return JLinkConnection(arguments, target)
