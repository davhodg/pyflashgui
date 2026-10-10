# pyflashgui manual

pyflashgui is a graphical flash programming tool for Arm Cortex-M targets, for any debug probe pyOCD supports.

**pyflashgui is at the start.** What is here is the application's frame: the window, its panes and workspaces. It does not connect to a probe or program anything yet, and this manual grows a page with each thing it learns to do.

## Contents

- [About, licences and updates](about.md)
- [Changes](changelog.md)

## The window

Everything pyflashgui has to say arrives in the **Event Log**, with warnings and errors in their own colours. A warning or an error opens the pane if it has been closed; an ordinary note does not. Right-click in it to clear it.

Each pane can be dragged to another edge of the window, floated, or closed, and **View** brings one back. *View > Reset layout* puts every pane back where it starts and the window back to the size it opens at.

*Tools > Settings > Theme* chooses light, dark, or whichever the operating system is set to.

## Where your files are

The arrangement of the panes and pyflashgui's settings are kept in a workspace, a folder under pyflashgui's own:

| | |
|---|---|
| Windows | `%APPDATA%\pyflashgui` |
| Linux | `~/.config/pyflashgui` |

*Tools > Open workspace folder* opens it.
