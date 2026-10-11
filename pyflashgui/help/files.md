[&larr; Contents](manual.md)

# Files

The **Files** pane is the list of what is to be programmed, and the buttons that do it.

## The list

**Add...** puts a firmware file on the list; **Remove** takes the selected ones off, and leaves the files themselves alone. Each file has a tick: only ticked files are programmed, verified and shown in the [Memory Map](memory-map.md). The list is kept in the workspace, so programming a product is choosing its workspace and pressing **Program**.

| Format | Addresses |
|---|---|
| ELF (`.elf`, `.axf`, `.out`) | In the file. Read at its load addresses, which is where initialised data is stored in flash. |
| Intel HEX (`.hex`) | In the file. |
| Motorola S-record (`.s19`, `.s28`, `.s37`, `.srec`) | In the file. |
| Raw binary (`.bin`) | None. Type where it starts into **Address**, in hexadecimal. |

The format is told from what is in the file, not from its name.

**A raw binary cannot be read until it has an address.** It is bytes and nothing else, and pyflashgui does not guess at zero. Double-click its **Address** and type one, such as `08000000`.

**A file is read again every time it is used**, and whenever it changes on disc, so the list and the Memory Map follow each build and **Program** always sends what the file holds now. A file that cannot be read says *Cannot be read* in the list; hover over it for why.

## Program, Verify, Erase, Reset

These need a probe [connected](probe.md) to a target.

- **Program** writes the ticked files. Before it starts, the files are checked against the target's memory, as the [Memory Map](memory-map.md) shows: if anything is an error there, nothing is programmed and the [Event Log](manual.md) says why.
- **Verify** reads the flash back and compares it with the ticked files, changing nothing. If they differ, it says how many bytes do and where the first one is.
- **Erase** erases all of the target's flash.
- **Reset** restarts the target.

Three ticks say what **Program** does besides writing:

- **Erase everything first** erases all of the flash before programming, so nothing of what was there is left. Without it, only the sectors the files write to are erased and the rest of the flash is kept.
- **Verify** reads the flash back afterwards and compares it.
- **Reset** restarts the target afterwards, so the new firmware runs. It is not reset if verifying failed.

**Program and Erase ask first**, once a session for each target, because what they replace cannot be got back. The question can be told not to ask again; *Tools > Reset > Re-enable all confirmations* brings it back. The simulated target is not asked about.

The bar beside the buttons says what is being done and how far along it is; where that cannot be told, it shows only that something is happening. **Cancel** stops a verify. Programming is not stopped part way: that would leave the target holding neither the old firmware nor the new.
