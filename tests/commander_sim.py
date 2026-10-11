# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A stand-in for SEGGER's J-Link Commander, for the tests.

It takes the command line and the command file the real one is given, keeps
a device's flash in a file between one run and the next, and answers in the
form the backend expects. That form is taken from SEGGER's documentation and
not from a J-Link: these tests show that pyflashgui asks for the right things
and copes with the answers it expects, and not that the real program gives
those answers.

Where it keeps things, and what it pretends, come from the environment:

    COMMANDER_SIM_HOME       a folder for the flash and for a record of each run
    COMMANDER_SIM_PROBES     "serial:product,serial:product"; "none" for none
    COMMANDER_SIM_NO_TARGET  set, and no device answers
    COMMANDER_SIM_SPOIL      an address whose byte is wrong after every LoadFile
"""

import json
import os
import shlex
import sys
from pathlib import Path

import bincopy

HOME = Path(os.environ["COMMANDER_SIM_HOME"])
FLASH = HOME / "flash.json"
RUNS = HOME / "runs.json"
DEVICES = (
    ("ST", "STM32F103ZE", "Cortex-M3"),
    ("Raspberry Pi", "RP2350_M33_0", "Cortex-M33"),
    ("TI", "AM2434_R5F0_0", "Cortex-R5"),
)
SECTOR = 0x1000
ERASED = 0xFF


def probes() -> list[tuple[str, str]]:
    listed = os.environ.get("COMMANDER_SIM_PROBES", "801012345:J-Link PLUS")
    if listed == "none":  # Windows has no such thing as a variable set to nothing
        return []
    return [tuple(item.split(":", 1)) for item in listed.split(",") if item]


def load() -> dict[int, int]:
    if not FLASH.exists():
        return {}
    return {int(address): value for address, value in json.loads(FLASH.read_text()).items()}


def save(flash: dict[int, int]) -> None:
    FLASH.write_text(json.dumps(flash))


def record(options: dict[str, str], commands: list[str]) -> None:
    runs = json.loads(RUNS.read_text()) if RUNS.exists() else []
    runs.append({"options": options, "commands": commands})
    RUNS.write_text(json.dumps(runs))


def fail(message: str, options: dict[str, str]) -> None:
    print(message)
    if options.get("-exitonerror") == "1":
        sys.exit(1)


def main() -> int:
    arguments = sys.argv[1:]
    options = {arguments[i].lower(): arguments[i + 1] for i in range(0, len(arguments) - 1, 2)}
    script = Path(options["-commandfile"])
    commands = [line.strip() for line in script.read_text().splitlines() if line.strip()]
    record(options, commands)

    print("pyflashgui's stand-in for J-Link Commander, for its tests")
    serials = [serial for serial, _product in probes()]
    wanted = options.get("-usb")
    if not serials or (wanted and wanted not in serials):
        fail("Connecting to J-Link via USB...FAILED: Cannot connect to J-Link.", options)
    device = options.get("-device")
    if device and device not in [name for _maker, name, _core in DEVICES]:
        fail(f"Unknown device '{device}' selected.", options)
    if options.get("-autoconnect") == "1" and os.environ.get("COMMANDER_SIM_NO_TARGET"):
        fail("Cannot connect to target.", options)

    flash = load()
    for line in commands:
        words = shlex.split(line)
        command = words[0].lower()
        if command == "exit":
            break
        if command == "showemulist":
            for index, (serial, product) in enumerate(probes()):
                print(
                    f"J-Link[{index}]: Connection: USB, Serial number: {serial}, "
                    f"ProductName: {product}"
                )
        elif command == "expdevlist":
            rows = ['"Manufacturer", "Device", "Core", "Flash areas", "RAM areas"']
            rows += [
                f'"{maker}", "{name}", "{core}", {{0x08000000, 0x00080000}}, '
                "{0x20000000, 0x00010000}"
                for maker, name, core in DEVICES
            ]
            Path(words[1]).write_text("\n".join(rows) + "\n")
        elif command == "erase":
            flash = {}
            print("Erasing done.")
        elif command == "loadfile":
            image = bincopy.BinFile()
            image.add_ihex_file(words[1])
            for segment in image.segments:
                first = segment.address // SECTOR * SECTOR
                last = -(-(segment.address + len(segment.data)) // SECTOR) * SECTOR
                for address in range(first, last):
                    flash.pop(address, None)
                for offset, value in enumerate(segment.data):
                    flash[segment.address + offset] = value
            if spoil := os.environ.get("COMMANDER_SIM_SPOIL"):
                flash[int(spoil, 0)] = flash.get(int(spoil, 0), ERASED) ^ 0xFF
            print("O.K.")
        elif command == "savebin":
            address, length = int(words[2], 0), int(words[3], 0)
            Path(words[1]).write_bytes(
                bytes(flash.get(address + offset, ERASED) for offset in range(length))
            )
        elif command in ("r", "h", "g"):
            pass
        else:
            fail(f"Unknown command. '{line}'", options)
    save(flash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
