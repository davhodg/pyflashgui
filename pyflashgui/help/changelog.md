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
- **Crop...** in a Memory pane makes a shorter copy of what is shown, as a read of its own:
  all of it but the erased bytes at the end, or a range. What erased flash reads as can be
  chosen there -- as the target says, `FF` or `00` -- and is kept for each target: an
  XMC4500's reads `00`. It takes the place of the tick beside Save, which made Save save
  less than was shown.
- **Stop when connecting** beside **Connect**, through pyOCD: untick it to attach to the target as it is,
  running, rather than stopping it. `flash.connect(stop=False)` in the console.
- **Program without erasing**, under the arrow beside **Program and verify**, writes to
  flash that **Erase...** has cleared already, so that it is not erased twice. Through
  pyOCD, and `flash.program(..., erase=False)` in the console. The tooltips of **Program
  and verify** and **Program** say that they erase the sectors they write to.

### Changed

- The name offered for saving a read is where it starts and how long it is, as eight
  hexadecimal digits each, in place of the date and time.
- Beside the progress bar, what is being done -- *Erasing...*, *Programming...*,
  *Verifying...* -- even where there is no figure for how far along it is, and each stage
  starts the bar afresh rather than leaving the last one's 100%. Programming through
  J-Link Commander says in the Event Log how long J-Link took to erase, and to program and
  check, or that the flash held the image already. Reading and verifying say how long
  they took, as erasing and programming do.
- The Python Console takes several lines at once: Shift+Enter for another, or several
  pasted, and Enter runs them together.
- **Reset** has the ways a target can be restarted under an arrow: the usual way, by
  the reset pin, by software, or the processor only. The one chosen is remembered for
  the target. An XMC4500 reset the usual way through pyOCD stayed stopped, and starts
  by its reset pin.
- Changing **Using** no longer keeps the target chosen for the last backend, which names
  targets its own way: each backend remembers its own, chosen again on switching back.
- **Compare** marks the other entry too when it is open in a Memory pane, and the Event Log
  says *Comparison result for* the one against the other.
- **Through** in the bar across the top is **Using**.
- A file in RAM is said to go to RAM, not flash, and to stay on the device until it is
  next reset: it read as though the file itself would be lost.
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
  under its arrow, in place of the Verify button and the Verify and Reset ticks.
  Programming leaves the target stopped, however it was done: **Reset** starts it.
- The launchers no longer ask about a Start menu entry: the first start says in the Event
  Log where a shortcut is made.

### Removed

- The **Erase everything first** tick. **Erase...** erases all of the flash.

### Fixed

- A pyOCD connect that failed kept hold of the probe, so every later one failed too until
  the backend was switched and back.
- Through pyOCD, a J-Link is now told the device's core, from its pack, so it reads and
  writes a block at a time: a megabyte in seconds rather than minutes. For a target with
  no pack the Event Log says reading and writing go a word at a time, and that J-Link
  Commander is quicker for it.
- With pyOCD's *cortex_m* chosen, which knows only the address map every Cortex-M has,
  a file for the device's flash was said to be in RAM. Programming is now refused with
  why, and to choose the device itself; reading and comparing still work.
- Programming through pyOCD ran the bar through **Programming** twice: the first time is
  pyOCD erasing the sectors it is about to write, and is now shown as **Erasing**.
- With the board's power turned off while connected through pyOCD, the probe could not be
  connected to again (*No emulator with serial number*) though Find probes found it:
  pyflashgui now lets go of the probe even when disconnecting from the target fails.
- A pack's device chosen as pyOCD spells it -- *xmc4500_f100x1024* for the pack's
  *xmc4500-f100x1024* -- was not known to be in the pack, so its core was not found. Both
  spellings are one device, listed once.
- An XMC4500 resets its debug port too when reset by its reset pin, and pyflashgui went
  on saying connected, so everything after failed with *Unspecified error*. A target that
  no longer answers after a reset is now connected to again, leaving it running, and the
  Event Log says so.
- Erasing or programming through pyOCD a target attached to as it ran -- an XMC4500 with
  its firmware going -- could end in a HardFault (*IPSR=3*): pyOCD ran its flash routine
  wherever it had stopped the firmware. The target is now reset and stopped first.
- Closing pyflashgui while connected could leave it waiting to let go of the probe, after
  a reset by the reset pin. Letting go is now given five seconds, on a thread of its own.
- Closing pyflashgui while it is working on the target, or while a script runs, says why
  it stays open in a box as well as in the Event Log.
- **Program without erasing** through pyOCD reads and writes back the rest of a page a
  file only partly covers, rather than filling it with `FF`: flash that reads `00` once
  erased, as an XMC4500's does, would have had `FF` written into it there.
- In the dark on Windows 10, an unticked box in a list (the Files pane, Erase) could hardly
  be seen; it now has an outline.
- In the Windows 11 style, a cell being edited (a binary's address in the Files pane) no
  longer shows its old value under the new one.

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
