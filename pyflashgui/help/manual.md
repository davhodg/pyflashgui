# pyflashgui manual

pyflashgui is a graphical flash programming tool: for Arm Cortex-M targets with any debug probe pyOCD supports, and for the many other devices a J-Link reaches through SEGGER's J-Link Commander.

![pyflashgui on its simulated probe: the Files pane with a firmware file and a read, the memory map under them, the bytes of the read beside them, and the Event Log below](main-window.png)

**It is a tool for the bench**: for development, debugging and hobby use. It is not meant for production programming.

## Contents

- [Probe and target](probe.md): the bar across the top, connecting, and which probes need what
- [Files](files.md): what is open, files and reads alike, and Read, Erase, Program and verify, Reset and Compare
- [Memory map](memory-map.md): where what is ticked lands, checked before anything is sent
- [Memory](memory.md): the bytes of a file or of what was read back, to look at, compare and save
- [Python Console](console.md): `flash` and scripts, for what the buttons do not do
- [About, licences and updates](about.md)
- [Changes](changelog.md)

## In short

1. Choose the **Probe** and the **Target** in the bar across the top.
2. **Add...** the firmware files in the Files pane.
3. Look at the memory map under the list: it says whether they fit the target.
4. **Connect**, then **Program and verify**, then **Reset** to start what was written.

With no hardware, choose *Simulated* under **Using** and the same steps work on a target that exists only in memory.

## The window

Everything pyflashgui has to say arrives in the **Event Log**, with warnings and errors in their own colours. A warning or an error opens the pane if it has been closed; an ordinary note does not. Right-click in it to clear it.

Each pane can be dragged to another edge of the window, floated, or closed, and **View** brings one back. *View > Reset layout* puts every pane back where it starts and the window back to the size it opens at.

*Tools > Settings > Theme* chooses light, dark, or whichever the operating system is set to.

## Workspaces

A workspace is everything about one thing being worked on: the probe, the target, its speed, the list of files and the arrangement of the panes. There is always one, called *default*, and somebody with one board never needs another.

*File > Workspace* is for when there is more than one:

- **New...** starts an empty one under a name: no files, and no probe or target chosen.
- **Save as...** keeps everything as it is now under a new name and carries on in that, leaving the one it came from as it was.
- **Switch to** opens another. The one in use is ticked, and the window's title names it unless it is *default*.
- **Manage...** renames or deletes one that is not in use. *default* is always there. Deleting one removes its settings and never the firmware files it listed.

There is no Save: a workspace is saved as it is changed. Switching reloads everything, so it asks first if a target is connected, since that target is let go of, and it waits while a target is being written to. What has been read and not saved is asked about as it is when pyflashgui is closed. The workspace last used is the one opened next time.

## Where your files are

Each workspace is a folder of its own, under pyflashgui's:

| | |
|---|---|
| Windows | `%APPDATA%\pyflashgui` |
| Linux | `~/.config/pyflashgui` |

*File > Workspace > Open folder* opens the one in use.
