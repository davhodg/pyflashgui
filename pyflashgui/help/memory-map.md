[&larr; Contents](manual.md)

# Memory Map

The **memory map** is the lower part of the [Files](files.md) pane. It shows what the ticked entries of the list above it -- files, and reads that have been ticked -- will write, and where, on the [target](probe.md) that is chosen. It is worked out before anything is sent, from the same bytes that will be sent, so a file linked for the wrong part is found here and not half way through programming a board. The bar between the list and the map can be dragged to give either more room.

From top to bottom:

- **What is wrong**, if anything is. Each line begins *Error* or *Warning*.
- **How full each flash region is**: the bytes the files write, out of the region's size, and how many sectors are erased to make room for them. A sector is erased whole, so one byte in a sector costs all of it.
- **Every piece of every file**: where it starts and ends, how big it is, and the region it lands in.

## What it finds

| | |
|---|---|
| **Error:** outside the target's memory | The file has bytes at addresses this target does not have. It was probably built for another part, or a raw binary has the wrong address. |
| **Error:** in memory that cannot be written | The bytes land in ROM, or in a region that is another address for the flash and takes no writes. |
| **Error:** two write the same addresses | Two files, or a file and a read. Whichever was written second would win, and which is second is not something anybody chose. Untick one of them. |
| **Warning:** in RAM | The bytes are written to the device's RAM, not its flash, and are gone from the device when it is next reset. The file itself is untouched. Loading a program into RAM to run it is a real thing to do; it is not what a file meant for flash should be doing. |
| **Error:** no device in particular | The target chosen is pyOCD's *cortex_m*, which knows only the address map every Cortex-M has: not where the device's flash is, nor how to program it. Reading and comparing work. To program, choose the device itself, from its pack if it is not built in. |

With an error showing, **Program** refuses. A warning does not stop it.

With *J-Link Commander*, bytes outside the memory listed for the device are a **warning** and not an error. SEGGER's list says where a device's memory is and may not give every address it can be reached at -- flash that also appears at a second address is listed once -- so pyflashgui does not refuse what SEGGER's software may take. That list does not say how flash is divided into sectors either, so for these devices the map says how full a region is and not how much is erased.

## When the memory is not known

A target that pyOCD has built in has its memory known as soon as it is chosen. One that comes from a CMSIS-Pack is known once it is connected to; until then the pieces are listed, files that overlap are still found, and the pane says that nothing has been checked against the target.
