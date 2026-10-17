[&larr; Contents](manual.md)

# Changes

What each version of pyflashgui added, changed and fixed, newest first. The format is [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and versions are numbered as [Semantic
Versioning](https://semver.org/spec/v2.0.0.html) describes. *Unreleased* is what has been done
since the last version, and comes out in the next one.

## [Unreleased]

### Added

- *View > Python Console*: a Python prompt and *Run script...*, with `flash` to connect,
  read, write RAM, erase, program, verify and reset, each call waiting for its answer.
- *File > Run script...* and *File > Recent scripts*, the last five run in the workspace.
- *Tools > pyOCD device packs...*: find a device that is not in the list of targets, and
  install the CMSIS-Pack that describes it, for use through pyOCD, or add a `.pack` file
  downloaded by hand for a computer with no internet. Every device is listed, narrowed as a
  name is typed, with the address its pack is downloaded from. An installed copy of
  pyflashgui had no way to add one.
- *File > Workspace*: a new workspace, the one in use saved under another name, switching
  between them, and renaming and deleting them.
- *Tools > Settings > Add shortcut to desktop* on Windows; both shortcuts for a pip
  installation too.

### Changed

- The speed box's first choice is **Default**, with what that comes to: 1 MHz through pyOCD,
  and auto through J-Link Commander. The Event Log says the speed on connecting.
- **Refresh** beside the probe is **Find probes**, and opening the list of probes looks
  again by itself when none was found. While it looks, the button says **Looking...**.
- The launchers notice a `.venv` whose Python has been uninstalled or replaced, and offer
  to make it again. On Windows, `.venv` is made from Python 3.14, 3.13 or 3.12 through
  the `py` launcher when one is installed, since every library has a ready-made download
  for them; a setup that fails no longer leaves a half-made `.venv` behind.
- The place for the Memory panes is kept beside the Files pane while none is open, saying
  how to fill it, rather than the Files pane taking the whole width. The pane arrangement
  saved by an earlier version is replaced by the default once.
- *Open workspace folder* is *File > Workspace > Open folder*, with the rest of what is
  done with a workspace.
- **Program and verify** is one button, with **Program** and **Verify** each on its own
  under its arrow, in place of the Verify button and the Verify and Reset ticks: the
  target is always restarted after programming.
- The launchers no longer ask about a Start menu entry: the first start says in the Event
  Log where a shortcut is made.

### Removed

- The **Erase everything first** tick. **Erase...** erases all of the flash.

### Fixed

- A pyOCD connect that failed kept hold of the probe, so every later one failed too until
  the backend was switched and back.

## [0.1.0] - 2026-10-11

### Added

- **Probe and target** in a bar across the top: the probe by its serial number, the
  target by name, the debug clock, and Connect. A simulated probe and target for trying
  pyflashgui with no hardware.
- **J-Link Commander** as a second way to a probe: a J-Link, through SEGGER's own
  software, for the devices beyond Cortex-M that it supports. SEGGER's software is not
  included.
- **Files**: a list of what is open -- ELF, Intel HEX, S-record and raw binary files, read
  again at each use and whenever one changes on disc, and what has been read from a
  target -- with a map underneath of where the ticked ones land, and Program, Verify,
  Erase, Reset and Read. A read can be ticked and written like a file, and any two
  entries can be compared.
- **Memory**: the bytes of each file and each read, as addresses, bytes and text, in a
  pane of its own that can be docked and tabbed, with a search for
  bytes or text and a way to an address. A read is saved from there as a raw binary,
  Intel HEX or S-record file, and is asked about before it is let go of unsaved.
  Through J-Link Commander, a read can leave out SEGGER's own setting up of the device, for
  a part where that changes its RAM.
- **A notice at the start**, each time, saying what programming a device can do and
  what to check first. The libraries load behind it.
- **Erase...**: all of a target's flash, some of its regions, or a range of addresses.
- **What the chosen target is**, at the foot of the window: its maker, its core where known,
  and how much flash and RAM it has.
- **Memory Map**: where the ticked files land on the chosen target, how full each flash
  region is, and what is wrong, worked out before anything is sent.
- The application's frame: the main window with dockable panes and the Event Log, workspaces,
  light and dark themes, the manual, and the Help menu with diagnostics, licences and a check
  for updates.
- Launchers for a source folder on Windows and Linux, and the build of the Windows installer.

[Unreleased]: https://github.com/davhodg/pyflashgui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/davhodg/pyflashgui/releases/tag/v0.1.0
