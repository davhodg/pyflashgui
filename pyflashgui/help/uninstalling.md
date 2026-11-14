[&larr; Contents](manual.md)

# Uninstalling

How depends on how pyflashgui was installed:

- **The Windows installer:** *Settings > Apps* (or *Add or remove programs*), or *Uninstall pyflashgui* in its Start menu folder. It takes away its shortcuts too.
- **pip:** `pip uninstall pyflashgui`, and what *Tools > Settings* added, as for a clone.
- **A Git clone:** delete the folder. If *Tools > Settings* was used to add a shortcut, take that away as well: the shortcuts are `%APPDATA%\Microsoft\Windows\Start Menu\Programs\pyflashgui.lnk` and `pyflashgui.lnk` on the desktop (on Linux, `~/.local/share/applications/pyflashgui.desktop`).

Your workspaces and settings are in `%APPDATA%\pyflashgui` (`~/.config/pyflashgui` on Linux), and no way of uninstalling touches them; delete that folder to remove them too.
