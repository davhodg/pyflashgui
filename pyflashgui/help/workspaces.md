[&larr; Contents](manual.md)

# Workspaces

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
