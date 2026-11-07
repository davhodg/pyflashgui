# Security policy

## Reporting a vulnerability

Please report it privately rather than in a public issue:
**[report a vulnerability](https://github.com/davhodg/pyflashgui/security/advisories/new)**,
which is also under the repository's *Security* tab.

Say what you found, how to make it happen, and which version or commit you
were running -- *Help > About pyflashgui* has a box to copy that from.

pyflashgui is looked after by one person in their own time, so there is no
promised response time. Every report is read and answered, the fix and the
advisory are published together, and you are credited in the advisory unless
you would rather not be.

## Versions that get fixes

The latest release and `master`. Older releases are not patched: upgrading
is the fix.

## What is and is not a vulnerability

pyflashgui is for writing to the flash of the device a debug probe is
connected to. Erasing and programming a target, and so replacing whatever was
on it, is the design and not a flaw in it.

What **is** worth reporting:

- a way to run code, or to write outside the folder you chose, from a file
  that is meant to be data -- a firmware image (ELF, Intel HEX, S-record or
  binary), a workspace's settings, or a CMSIS-Pack: a `.pack` file added from
  disc, or a pack or the list of packs downloaded through *Tools > pyOCD
  device packs*;
- pyflashgui going online when you did not ask it to. It is designed to go
  online only for *Help > Check for updates*, for fetching the list of packs
  or installing a pack in *Tools > pyOCD device packs*, and for a page you
  chose to open;
- erasing or programming a target without asking first -- unless you told it
  to stop asking -- or after you declined. It is designed to ask, but those
  questions are a reminder rather than a safeguard, and pyflashgui is provided
  without warranty of any kind.

What is **not**, here:

- a debug port giving full access to a device. That is what a debug port is;
  protecting one belongs to the device's own read-out protection and to its
  maker;
- a pack's flash routine running on the target. Programming a device through
  its pack is what the routine is for, so install packs from their makers;
- problems in the libraries pyflashgui is built on -- Qt, pyOCD, libusb and
  the rest, or a probe vendor's own software. Report those upstream; do tell
  us if pyflashgui uses one unsafely.
