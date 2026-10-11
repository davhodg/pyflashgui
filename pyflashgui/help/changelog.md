[&larr; Contents](manual.md)

# Changes

What each version of pyflashgui added, changed and fixed, newest first. The format is [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/), and versions are numbered as [Semantic
Versioning](https://semver.org/spec/v2.0.0.html) describes. *Unreleased* is what has been done
since the last version, and comes out in the next one.

## [Unreleased]

## [0.1.0] - not yet released

### Added

- **Probe and target** in a bar across the top: the probe by its serial number, the
  target by name, the debug clock, and Connect. A simulated probe and target for trying
  pyflashgui with no hardware.
- **J-Link Commander** as a second way to a probe: a J-Link, through SEGGER's own
  software, for the devices beyond Cortex-M that it supports. SEGGER's software is not
  included.
- **Files**: a list of ELF, Intel HEX, S-record and raw binary files, read again at each
  use and whenever one changes on disc, with Program, Verify, Erase and Reset.
- **Read...** in the Files pane: part of a target's memory read back into a raw binary,
  Intel HEX or S-record file.
- **Memory Map**: where the ticked files land on the chosen target, how full each flash
  region is, and what is wrong, worked out before anything is sent.
- The application's frame: the main window with dockable panes and the Event Log, workspaces,
  light and dark themes, the manual, and the Help menu with diagnostics, licences and a check
  for updates.
- Launchers for a source folder on Windows and Linux, and the build of the Windows installer.

[Unreleased]: https://github.com/davhodg/pyflashgui/commits/master
[0.1.0]: https://github.com/davhodg/pyflashgui/commits/master
