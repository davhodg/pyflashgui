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

A graphical flash programming tool for Arm Cortex-M targets that works with any debug probe [pyOCD](https://pyocd.io) supports: CMSIS-DAP probes such as the Raspberry Pi Debug Probe, DAPLink, NXP MCU-Link and Atmel-ICE, the probes built into many development boards, ST-Link and TI XDS110.

**pyflashgui is new.** Reading files, the memory map and everything on screen are tested against a simulated probe. Programming a real device through pyOCD has not yet been tried on hardware.

## Install and run

To install it:

```
pip install pyflashgui
```

To run it:

```
pyflashgui
```

It needs Python 3.12 or newer, on Windows or Linux.

## More

The [README](https://github.com/davhodg/pyflashgui#readme) says which probes need which drivers, and the [manual](https://github.com/davhodg/pyflashgui/blob/master/pyflashgui/help/manual.md) ships inside pyflashgui, under *Help > Documentation*.

Apache-2.0.
