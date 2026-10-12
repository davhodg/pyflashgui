<p align="center">
  <img src="https://raw.githubusercontent.com/davhodg/pyflashgui/master/pyflashgui/resources/pyflashgui.png" alt="pyflashgui icon: a chip with pins on every side and a flash across it" width="128">
</p>

# pyflashgui

[![CI](https://github.com/davhodg/pyflashgui/actions/workflows/ci.yml/badge.svg)](https://github.com/davhodg/pyflashgui/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/davhodg/pyflashgui?include_prereleases)](https://github.com/davhodg/pyflashgui/releases)
[![PyPI](https://img.shields.io/pypi/v/pyflashgui)](https://pypi.org/project/pyflashgui/)
![python](https://img.shields.io/badge/python-3.12+-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
![license](https://img.shields.io/badge/license-Apache--2.0-green)

A graphical flash programming tool. It works with any debug probe [pyOCD](https://pyocd.io) supports, for Arm Cortex-M targets: CMSIS-DAP probes such as the Raspberry Pi Debug Probe, DAPLink, NXP MCU-Link and Atmel-ICE, TI XDS110 and the probes built into many development boards, as well as ST-Link and J-Link. With a J-Link it can also use SEGGER's J-Link Commander, for the many other devices that supports.

![pyflashgui on its simulated probe: the Files pane with a firmware file and a read, the memory map under them, the bytes of the read beside them, and the Event Log below](https://raw.githubusercontent.com/davhodg/pyflashgui/master/pyflashgui/help/main-window.png)

## Install and run

To install it:

```
pip install pyflashgui
```

To run it:

```
pyflashgui
```

To update it:

```
pip install --upgrade pyflashgui
```

Python 3.12 or newer, on Windows or Linux. `python -m pyflashgui` starts it too.

On Linux, Qt needs a system library to draw the window, and Debian, Ubuntu, Linux Mint and the like often leave it out:

```
sudo apt install libxcb-cursor0
```

A probe is usable without root on Linux once a udev rule allows it; pyOCD publishes [a set of them](https://github.com/pyocd/pyOCD/tree/main/udev).

## What it does

- **Probe and target** in a bar across the top: the probe by its serial number, the target by name, the debug clock, and Connect.
- **Files**: ELF, Intel HEX, Motorola S-record and raw binary, in one list with what has been read from a target. A file is read again whenever a build writes it.
- **Memory map**: where everything ticked will land on the chosen target, how full each flash region is and how much is erased, checked before anything is sent. A file built for another part, or two that write the same addresses, are found here.
- **Program and verify** in one press, with each half on its own beside it, **Erase** of all the flash, some regions or a range, and **Reset**.
- **Read** any range of a target's memory back, shown as addresses, bytes and text, with a search for bytes or text and a way to an address. A read is saved as raw binary, Intel HEX or S-record, and can be programmed like a file.
- **Compare** any two of them -- what is in the target against the file that should be, or one read against another -- with each difference marked.
- **Workspaces**: one for each board or project, holding its probe, target, files and layout.
- **A simulated probe and target**, to try all of it with no hardware.

The [manual](https://github.com/davhodg/pyflashgui/blob/master/pyflashgui/help/manual.md) covers each of these, and is also under **Help > Documentation** in the application.

## Probes and targets

Through [pyOCD](https://pyocd.io), any probe it supports, for Arm Cortex-M targets: CMSIS-DAP probes, ST-Link, and J-Link. The targets are those pyOCD has built in and those in the CMSIS-Packs installed on the computer.

Through SEGGER's J-Link Commander, a J-Link reaches the devices beyond Cortex-M that SEGGER's software supports -- Cortex-A and Cortex-R, RISC-V and others. SEGGER's software is not included: install it, and pyflashgui finds it.

The [README](https://github.com/davhodg/pyflashgui#probes) says which probes need which drivers.

## More

- [Source, issues and releases](https://github.com/davhodg/pyflashgui)
- [Standalone Windows installer](https://github.com/davhodg/pyflashgui/releases)
- [Questions and ideas](https://github.com/davhodg/pyflashgui/discussions)
- [Manual](https://github.com/davhodg/pyflashgui/blob/master/pyflashgui/help/manual.md)

## Safety notice and licence

pyflashgui talks to real equipment. It is intended only for people trained and experienced in working with microcontrollers, debug probes and the equipment they are part of. It is a tool for development and the bench, and is not meant for production programming.

Erasing and programming replace what a device holds, and cannot be undone. A device given the wrong file, or one that changes its protection or configuration, may not run, and may no longer be reachable through its debug port. Connecting, resetting and reading can stop or restart a device that is running, and with it whatever that device controls.

Like any software, pyflashgui can have faults, so do not rely on it alone to say that a device holds what was meant. Where a mistake could hurt someone or damage equipment, keep a way to stop that equipment within reach.

pyflashgui is provided under the Apache License 2.0, without warranty of any kind.
