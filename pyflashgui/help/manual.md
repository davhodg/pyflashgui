# pyflashgui manual

pyflashgui is a graphical flash programming tool: for Arm Cortex-M targets with any debug probe pyOCD supports, and for the many other devices a J-Link reaches through SEGGER's J-Link Commander.

**pyflashgui is new.** Reading files, the memory map and everything on screen are tested against a simulated probe. On hardware, only reading through J-Link Commander has been tried so far, on one board; programming a real device has not.

**It is a tool for the bench**: for development, debugging and hobby use. It is not meant for production programming.

## Contents

- [Probe and target](probe.md): the bar across the top, connecting, and which probes need what
- [Files](files.md): what is programmed, and Program, Verify, Erase and Reset
- [Memory Map](memory-map.md): where the files land, checked before anything is sent
- [Memory](memory.md): what was read back from a target, to look at and to save
- [About, licences and updates](about.md)
- [Changes](changelog.md)

## In short

1. Choose the **Probe** and the **Target** in the bar across the top.
2. **Add...** the firmware files in the Files pane.
3. Look at the Memory Map: it says whether they fit the target.
4. **Connect**, then **Program**.

With no hardware, choose *Simulated* under **Through** and the same steps work on a target that exists only in memory.

## The window

Everything pyflashgui has to say arrives in the **Event Log**, with warnings and errors in their own colours. A warning or an error opens the pane if it has been closed; an ordinary note does not. Right-click in it to clear it.

Each pane can be dragged to another edge of the window, floated, or closed, and **View** brings one back. *View > Reset layout* puts every pane back where it starts and the window back to the size it opens at.

*Tools > Settings > Theme* chooses light, dark, or whichever the operating system is set to.

## Where your files are

The probe, the target, the list of files, the arrangement of the panes and pyflashgui's settings are kept in a workspace, a folder under pyflashgui's own:

| | |
|---|---|
| Windows | `%APPDATA%\pyflashgui` |
| Linux | `~/.config/pyflashgui` |

*Tools > Open workspace folder* opens it.
