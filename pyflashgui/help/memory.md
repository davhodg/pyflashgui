[&larr; Contents](manual.md)

# Memory

Each read of a target opens a **Memory** pane of its own, showing what was read: sixteen bytes to a row, with the address of the first, the bytes in hexadecimal, and the characters they spell. The first is called *Memory*, the next *Memory 2*, and so on, each with the address it was read from and how much. A second read leaves the first as it was, so two reads can be looked at side by side.

A Memory pane opens in front of the window, and is a pane like any other: it can be docked at an edge, tabbed with another pane, or given a window of its own, and **View** lists it. **Once one is docked in the window, the next read opens as a tab beside it**, so putting the first where it is wanted puts the rest there too.

**What is in a Memory pane is nowhere else until it is saved.** It is not kept with the workspace, and closing the pane closes it for good, where closing another pane only puts it away. So closing one that has not been saved says so first, and offers to save it, to discard it, or to leave it open. Closing pyflashgui asks the same of each one that is open.

## Reading

**Read...**, in the [Files](files.md) pane or in a Memory pane, asks what to read. It needs a probe [connected](probe.md) to a target, and changes nothing in the target.

- **Region** offers the target's own regions, the flash first, and fills in the address and the length. Both can be typed over, in hexadecimal: what is wanted is as often the first few kilobytes as the whole region.
- Where the target's memory is not known, as for a device whose name was typed and is not on the backend's list, there are no regions to choose and the range is typed.
- **Leave the device as it is (skip J-Link's own set-up)** is offered with J-Link Commander only. On connecting, SEGGER's software sets some devices up in ways that change them: on an S32K3 it fills the RAM, so a read made to see what a running program left there finds it gone. With this ticked, that set-up is left out for this read. It is not ticked to begin with, and wants leaving alone unless that is the trouble: on a part whose set-up is what lets it be read at all, a read without it fails. Programming and erasing always have the set-up.

What is read is kept in memory and shown in a new pane. The line above the bytes says which target it came from, the range and when. The bar in the Files pane shows how far along a read is, and **Cancel** there stops it.

A device that protects its flash from being read gives an error from the probe, or reads as something other than what it holds. pyflashgui does not try to get round that.

## Finding your way about

Both of these work on what was read, and read nothing more from the target.

- **Go to** takes an address in hexadecimal and, on Enter, goes to the row it is on. An address outside what was read is said, with the range that was.
- **Find** looks for **Bytes**, typed in hexadecimal, or for **Text**, as it is spelled. Bytes can be typed however is convenient: `DE AD BE EF`, `DEADBEEF` and `0xDE, 0xAD, 0xBE, 0xEF` are the same four. Text is matched exactly, capitals included. Enter or **Next** finds the next, **Previous** the one before, and the search goes round from the end to the start, saying so when it does.

The line under the boxes says the address of what was found. The row is selected as well, but a row is sixteen bytes and the address is the one that was meant.

| | |
|---|---|
| Ctrl+F | Find |
| F3, Shift+F3 | The next, and the one before |
| Ctrl+G | Go to an address |

The keys work in the Memory pane that is being used.

## Comparing with a file

**Compare...** asks for a firmware file and marks where what is shown differs from it. It works on what was already read, and reads nothing more from the target. It is the question [Verify](files.md) asks, of any stretch of memory and at any time after it was read.

- **Only where the two overlap is compared.** A file and a read rarely cover the same addresses. What the file has outside what was read, and what was read that the file says nothing about, are each counted and said, and neither is a difference.
- **A line says what was found**: how many bytes were compared, how many differ and where the first is. The same line goes to the Event Log.
- **A File column appears**, with something in it on each row that differs: the file's own bytes where they differ, `..` for a byte that agrees and `--` for one the file does not mention. A row that agrees throughout is left blank.
- **Next difference** and **Previous difference** go from one stretch of differing bytes to the next, going round, and say where it is and what each side has.

A raw binary has no addresses of its own, so it is taken to start where what was read starts. The comparison is that pane's: another read, in another pane, has none until it is compared for itself.

## Saving

**Save...** writes what is shown to a file: a raw binary, Intel HEX or Motorola S-record, by the name it is given. Nothing is saved until this is pressed, so a read made only to look costs no file. Once it has been saved, the pane closes without asking.

- A raw binary is the bytes and nothing else, so it does not record where they came from. The other two do, and can be put on the [Files](files.md) list and programmed back as they are.
- An S-record file is given addresses wide enough for what it holds, whatever its name: flash at `08000000` saved as `.s19` has 32-bit addresses.
- **Leave off the erased bytes at the end** is for a read of more than is there. Erased flash reads as `FF`, so the whole of a 1 MiB flash holding 100 KiB of firmware saves as 1 MiB. With this ticked, the file ends at the last byte that holds something; an `FF` in the middle of what is there is kept. It is not ticked to begin with, so that what is saved is what was read.
