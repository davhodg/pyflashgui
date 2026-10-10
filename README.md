<p align="center">
  <img src="pyflashgui/resources/pyflashgui.png" alt="pyflashgui icon: a chip with pins on every side and a flash across it" width="128">
</p>

# pyflashgui

[![CI](https://github.com/davhodg/pyflashgui/actions/workflows/ci.yml/badge.svg)](https://github.com/davhodg/pyflashgui/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/davhodg/pyflashgui?include_prereleases)](https://github.com/davhodg/pyflashgui/releases)
[![PyPI](https://img.shields.io/pypi/v/pyflashgui)](https://pypi.org/project/pyflashgui/)
![python](https://img.shields.io/badge/python-3.12+-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
![license](https://img.shields.io/badge/license-Apache--2.0-green)

A graphical flash programming tool for Arm Cortex-M targets that works with any debug probe [pyOCD](https://pyocd.io) supports: CMSIS-DAP probes such as the Raspberry Pi Debug Probe, and ST-Link.

**pyflashgui is at the start.** What is here is the application's frame -- the window, its panes, workspaces, the manual, the build and the installer. It does not connect to a probe or program anything yet.

## What it is for

- **Any probe.** A low-cost CMSIS-DAP probe or the ST-Link on a development board does the job a dedicated programmer does.
- **Workspaces.** The target, the probe, its speed and the files to program are kept together, one workspace per product, so programming a board is one click.
- **Production.** Programming as each board is connected, with a pass or fail logged for every one.
- **Files.** ELF, Intel HEX, Motorola S-record and raw binary, with a map of what will be written where.

## Run it from a source folder

```
git clone https://github.com/davhodg/pyflashgui
```

then `pyflashgui.cmd` on Windows or `./pyflashgui.sh` on Linux. The first run makes a `.venv` in the folder and installs what pyflashgui needs into it, which takes a few minutes; every later start is immediate. It needs Python 3.12 or newer.

## Probes and drivers

| Probe | Windows | Linux |
|---|---|---|
| CMSIS-DAP v2 (Raspberry Pi Debug Probe and others) | no driver needed | a udev rule |
| ST-Link | ST's driver | a udev rule |

On Linux a probe is usable without root once a udev rule allows it; pyOCD publishes [a set of them](https://github.com/pyocd/pyOCD/tree/main/udev). Vendor software is never bundled with pyflashgui: install the vendor's own, and pyflashgui finds it.

## Built with

| Package | For | Licence |
|---|---|---|
| [PySide6](https://www.qt.io/qt-for-python) (Essentials) | the windows | LGPL-3.0 |
| [pyOCD](https://pyocd.io) | probes, targets and flash algorithms | Apache-2.0 |
| [bincopy](https://github.com/eerimoq/bincopy) | Intel HEX, S-record and binary files | MIT |

## Uninstalling

A source folder: delete the folder. An installed build: *Settings > Apps* on Windows. Your workspaces and settings are in `%APPDATA%\pyflashgui` on Windows and `~/.config/pyflashgui` on Linux, and are left alone by upgrading and by uninstalling; delete that folder to remove them too.

## Licence

Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Security problems go through [SECURITY.md](SECURITY.md).
