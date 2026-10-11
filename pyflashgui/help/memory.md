[&larr; Contents](manual.md)

# Memory

The **Memory** pane shows what was last read from a target: sixteen bytes to a row, with the address of the first, the bytes in hexadecimal, and the characters they spell. It opens in a window of its own the first time something is read, and can be docked like any other pane.

## Reading

**Read...**, here or in the [Files](files.md) pane, asks what to read. It needs a probe [connected](probe.md) to a target, and changes nothing in the target.

- **Region** offers the target's own regions, the flash first, and fills in the address and the length. Both can be typed over, in hexadecimal: what is wanted is as often the first few kilobytes as the whole region.
- Where the target's memory is not known, as for a device whose name was typed and is not on the backend's list, there are no regions to choose and the range is typed.
- **Leave the device as it is (skip J-Link's own set-up)** is offered with J-Link Commander only. On connecting, SEGGER's software sets some devices up in ways that change them: on an S32K3 it fills the RAM, so a read made to see what a running program left there finds it gone. With this ticked, that set-up is left out for this read. It is not ticked to begin with, and wants leaving alone unless that is the trouble: on a part whose set-up is what lets it be read at all, a read without it fails. Programming and erasing always have the set-up.

What is read is kept in memory and shown, in place of whatever was read before. The line above the bytes says which target it came from, the range and when. The bar in the Files pane shows how far along a read is, and **Cancel** there stops it.

A device that protects its flash from being read gives an error from the probe, or reads as something other than what it holds. pyflashgui does not try to get round that.

## Saving

**Save...** writes what is shown to a file: a raw binary, Intel HEX or Motorola S-record, by the name it is given. Nothing is saved until this is pressed, so a read made only to look costs no file.

- A raw binary is the bytes and nothing else, so it does not record where they came from. The other two do, and can be put on the [Files](files.md) list and programmed back as they are.
- An S-record file is given addresses wide enough for what it holds, whatever its name: flash at `08000000` saved as `.s19` has 32-bit addresses.
- **Leave off the erased bytes at the end** is for a read of more than is there. Erased flash reads as `FF`, so the whole of a 1 MiB flash holding 100 KiB of firmware saves as 1 MiB. With this ticked, the file ends at the last byte that holds something; an `FF` in the middle of what is there is kept. It is not ticked to begin with, so that what is saved is what was read.
