[&larr; Contents](manual.md)

# Memory Map

The **Memory Map** pane shows what the ticked [files](files.md) will write, and where, on the [target](probe.md) that is chosen. It is worked out before anything is sent, from the same bytes that will be sent, so a file linked for the wrong part is found here and not half way through programming a board.

From top to bottom:

- **What is wrong**, if anything is. Each line begins *Error* or *Warning*.
- **How full each flash region is**: the bytes the files write, out of the region's size, and how many sectors are erased to make room for them. A sector is erased whole, so one byte in a sector costs all of it.
- **Every piece of every file**: where it starts and ends, how big it is, and the region it lands in.

## What it finds

| | |
|---|---|
| **Error:** outside the target's memory | The file has bytes at addresses this target does not have. It was probably built for another part, or a raw binary has the wrong address. |
| **Error:** in memory that cannot be written | The bytes land in ROM, or in a region that is another address for the flash and takes no writes. |
| **Error:** two files write the same addresses | Whichever was written second would win, and which is second is not something anybody chose. |
| **Warning:** in RAM | The bytes are written, and lost at the next reset. Loading a program into RAM to run it is a real thing to do; it is not what a file meant for flash should be doing. |

With an error showing, **Program** refuses. A warning does not stop it.

## When the memory is not known

A target that pyOCD has built in has its memory known as soon as it is chosen. One that comes from a CMSIS-Pack is known once it is connected to; until then the pieces are listed, files that overlap are still found, and the pane says that nothing has been checked against the target.
