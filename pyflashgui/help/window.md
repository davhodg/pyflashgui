[&larr; Contents](manual.md)

# The window

## Event Log

Everything pyflashgui has to say arrives in the **Event Log**, with warnings and errors in their own colours. A warning or an error opens the pane if it has been closed; an ordinary note does not. Right-click in it for *Save all...*, which writes it to a text file, and *Clear all*, which empties it. An error pyOCD or pylink reports for itself is put here too, named after the library; their other lines are kept for *Help > Diagnostics*. *Tools > Settings > Time on Event Log lines* puts the time of day each line was written in front of it, to the second -- *14:03:27 Connected ...* -- from the next line on, and it is kept when the log is copied. It is off to begin with, and kept with this computer rather than the workspace, like the theme.

## Panes

Each pane can be dragged to another edge of the window, floated, or closed, and **View** brings one back. *View > Reset layout* puts every pane back where it starts and the window back to the size it opens at.

## Theme

*Tools > Settings > Theme* chooses light, dark, or whichever the operating system is set to. Which look Qt draws it in depends on the system:

| System | Style |
|---|---|
| Windows 11 | Qt's Windows 11 style, light and dark |
| Windows 10 and earlier | Qt's style for these has no dark version, so Qt's Fusion style, light and dark alike |
| Linux | Usually Fusion, or the desktop's own Qt style where it sets one |

The style in use is shown greyed out at the bottom of the *Theme* menu, and in the menu's tooltip, and *Help > Diagnostics...* gives it with the theme.

## Icons

*Tools > Settings > Show icons* puts a standard icon beside the word on common buttons and menu items -- Connect, Erase, Save, Stop and the like -- to find them at a glance. It is on to start with; untick it for the words alone. The words are there either way, and the choice is kept for you on this computer. The icons are Microsoft's Fluent UI System Icons, shipped with pyflashgui, so they are the same on Windows and Linux, drawn in the theme's text colour.
