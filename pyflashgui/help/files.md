[&larr; Contents](manual.md)

# Files

The **Files** pane is the list of what is open, a map of where it lands, and the buttons that use it. What is open is firmware files and what has been read from a target, and the two are treated alike: each is bytes at addresses, to look at, to compare and to write.

## The list

**Add...** puts a firmware file on the list, and **Read...** puts what it reads from the target there, as *Read 1*, *Read 2* and so on. Each row says what it is, where it came from, the addresses it runs from and to, and its size. **Remove** takes the selected ones off: a file itself is left alone, and a read that has not been saved is asked about first.

Each has a tick: only what is ticked is programmed, verified and shown in the [memory map](memory-map.md) underneath. A file is ticked when it is added. **A read is not**, since most are made to be looked at; tick one to write it to a target like a file, beside the files or instead of them. The files are kept in the workspace, so programming a product is choosing its workspace and pressing **Program**. What was read is in memory until it is saved, and is not kept.

**Show**, or a double click, shows the bytes of an entry in a [Memory](memory.md) pane. One opens by itself for each file and each read as it joins the list.

**Compare** compares the two entries that are selected -- two reads, two files, or one of each -- and marks where they differ in a Memory pane. Ctrl+click selects the second. See [Comparing](memory.md).

| Format | Addresses |
|---|---|
| ELF (`.elf`, `.axf`, `.out`) | In the file. Read at its load addresses, which is where initialised data is stored in flash. |
| Intel HEX (`.hex`) | In the file. |
| Motorola S-record (`.s19`, `.s28`, `.s37`, `.srec`) | In the file. |
| Raw binary (`.bin`) | None. Type where it starts into **Address**, in hexadecimal. |

The format is told from what is in the file, not from its name.

**A raw binary cannot be read until it has an address.** It is bytes and nothing else, and pyflashgui does not guess at zero. Double-click its **Address** and type one, such as `08000000`.

**A file is read again every time it is used**, and whenever it changes on disc, so the list, the memory map and the file's Memory pane follow each build and **Program** always sends what the file holds now. A file that cannot be read says *Cannot be read* in the list; hover over it for why.

## Read, Erase, Program and verify, Reset

These need a probe [connected](probe.md) to a target.

- **Read...** reads part of the target's memory back, changing nothing in the target. What is read joins the list and is shown in a [Memory](memory.md) pane of its own. It can be saved to a file from there.
- **Erase...** erases the target's flash: all of it, some of its regions, or a range of addresses. See *Erasing* below.
- **Program and verify** writes what is ticked -- files, reads, or both -- then reads the flash back to check it holds what was written, and restarts the target so that the new firmware runs. Before it starts, what is ticked is checked against the target's memory and against each other, as the [memory map](memory-map.md) shows: if anything is an error there -- two of them writing the same addresses is one -- nothing is programmed and the [Event Log](manual.md) says why. The arrow beside it has each half on its own:
  - **Program** writes and restarts without the check: quicker for a large image.
  - **Verify** reads the flash back and compares it with what is ticked, changing nothing and restarting nothing. If they differ, it says how many bytes do and where the first one is.
- **Reset** restarts the target.

Programming erases only the sectors it writes to, and the rest of the flash is kept; to clear all of it first, use **Erase...**. The target is restarted afterwards, since programming leaves it halted, but not if the check failed.

**Program and Erase ask first**, once a session for each target, because what they replace cannot be got back. The question can be told not to ask again; *Tools > Reset > Re-enable all confirmations* brings it back. The simulated target is not asked about.

The bar beside the buttons says what is being done and how far along it is; where that cannot be told, it shows only that something is happening. **Cancel** stops a verify or a read. Programming is not stopped part way: that would leave the target holding neither the old firmware nor the new.

## Erasing

**Erase...** asks how much, and opens on **All of the flash**.

- **These regions** lists the target's flash regions, each with a tick. It is for a device with more than one flash, where the bootloader or the data is to be kept.
- **This range** takes an address and a length, in hexadecimal.

Flash is erased a sector at a time, so every sector that any of a range falls in is erased whole: a range of sixteen bytes costs the sector they are in. Where the target's memory is not known there are no regions to tick, and the choice is all of it or a range.

Before anything is erased, pyflashgui says which addresses will go and asks, as it does before programming.

