[&larr; Contents](manual.md)

# Memory

A **Memory** pane shows the bytes of one entry of the [Files](files.md) list -- a firmware file, or what was read from a target: sixteen bytes to a row, with the address of the first, the bytes in hexadecimal, and the characters they spell. Each entry has a pane of its own, opened when it joins the list. Each is called what the list calls it: the file's name, or *Read 1*, *Read 2* and so on.

A file in several pieces, with nothing between them, is shown piece after piece: each starts a row of its own at its own address, and the gaps are not shown.

Memory panes open beside the Files pane, as tabs of one another. Each is a pane like any other: it can be docked at an edge, tabbed with another pane, or given a window of its own, and **View** lists it. A new one opens as a tab with the last that is docked in the window, so moving one moves where the rest arrive.

**Closing a Memory pane loses nothing.** What it showed is still on the Files list, and **Show** there, or a double click, opens it again. It is taking a read off that list, or closing pyflashgui, that would lose one that has not been saved, and both say so first and offer to save it, to discard it, or to keep it. The pane of a file follows the file: when a build writes it again, the pane shows what it holds now.

## Reading

**Read...**, in the [Files](files.md) pane or in a Memory pane, asks what to read. It needs a probe [connected](probe.md) to a target, and changes nothing in the target.

- **Region** offers the target's own regions, the flash first, and fills in the address and the length. Both can be typed over, in hexadecimal: what is wanted is as often the first few kilobytes as the whole region.
- Where the target's memory is not known, as for a device whose name was typed and is not on the backend's list, there are no regions to choose and the range is typed.
- **Leave the device as it is (skip J-Link's own set-up)** is offered with J-Link Commander only. On connecting, SEGGER's software sets some devices up in ways that change them: on an S32K3 it fills the RAM, so a read made to see what a running program left there finds it gone. With this ticked, that set-up is left out for this read. It is not ticked to begin with, and wants leaving alone unless that is the trouble: on a part whose set-up is what lets it be read at all, a read without it fails. Programming and erasing always have the set-up.

What is read is kept in memory, joins the Files list and is shown in a new pane. The line above the bytes says which target it came from, the range and when. The bar in the Files pane shows how far along a read is, and **Cancel** there stops it.

A device that protects its flash from being read gives an error from the probe, or reads as something other than what it holds. pyflashgui does not try to get round that.

## Finding your way about

Both of these work on what is shown, and read nothing more from the target.

- **Go to** takes an address in hexadecimal and, on Enter, goes to the row it is on. An address outside what was read is said, with the range that was.
- **Find** looks for **Bytes**, typed in hexadecimal, or for **Text**, as it is spelled. Bytes can be typed however is convenient: `DE AD BE EF`, `DEADBEEF` and `0xDE, 0xAD, 0xBE, 0xEF` are the same four. Text is matched exactly, capitals included. Enter or **Next** finds the next, **Previous** the one before, and the search goes round from the end to the start, saying so when it does.

The line under the boxes says the address of what was found. The row is selected as well, but a row is sixteen bytes and the address is the one that was meant.

| | |
|---|---|
| Ctrl+F | Find |
| F3, Shift+F3 | The next, and the one before |
| Ctrl+G | Go to an address |

The keys work in the Memory pane that is being used.

## Comparing

**Compare**, in the [Files](files.md) pane, compares the two entries selected there: two reads, two files, or a read and a file. One of them is shown, marked where the other differs from it. Of a read and a file it is the read that is shown, the file being what the target is held against; of two of a kind, the one higher in the list. Nothing is read from the target. It is the question [Verify](files.md) asks, of any stretch of memory and at any time after it was read.

- **Only where the two overlap is compared.** Two of them rarely cover the same addresses. What the other has outside what is shown, and what is shown that the other says nothing about, are each counted and said, and neither is a difference.
- **A line says what was found**: how many bytes were compared, how many differ and where the first is. The Event Log has it too, as the comparison result for the one shown against the other.
- **If the other is open in a Memory pane as well**, it is marked against the first, so the differences can be looked at from either side.
- **A column appears, headed with the other's name**, with something in it on each row that differs: the other's own bytes where they differ, `..` for a byte that agrees and `--` for one the other does not mention. A row that agrees throughout is left blank.
- **Next difference** and **Previous difference** go from one stretch of differing bytes to the next, going round, and say where it is and what each side has.

To compare with a file that is not on the list, add it; untick it if it is not to be programmed. A raw binary has no addresses of its own, so it needs its address typed in the list before it can be compared. The comparison is that pane's, and showing something else in it, or the file changing, puts it away.

## Saving

**Save...** writes what is shown to a file: a raw binary, Intel HEX or Motorola S-record, by the name it is given. Nothing is saved until this is pressed, so a read made only to look costs no file. Once it has been saved, the Files list no longer says *not saved*, and it is removed without asking. Save is for what is in one piece, as everything read from a target is.

- A raw binary is the bytes and nothing else, so it does not record where they came from. The other two do, and can be put on the [Files](files.md) list and programmed back as they are.
- An S-record file is given addresses wide enough for what it holds, whatever its name: flash at `08000000` saved as `.s19` has 32-bit addresses.
- **Leave off the erased bytes at the end** is for a read of more than is there. Erased flash reads as `FF` on most devices, so the whole of a 1 MiB flash holding 100 KiB of firmware saves as 1 MiB. With this ticked, the file ends at the last byte that holds something; an erased byte in the middle of what is there is kept. Some devices' flash reads `00` once erased -- an XMC4500's does -- and through pyOCD the device's own erased value is used, from its pack. It is not ticked to begin with, so that what is saved is what was read.
