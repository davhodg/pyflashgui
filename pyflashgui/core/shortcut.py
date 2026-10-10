# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A Start menu or applications menu entry for a source folder.

The installer makes its own. A clone has only the launcher, and the entry made
here points at that rather than at the Python in ``.venv``: the launcher is
what notices a dependency added since the last pull, so starting from the menu
picks up an update exactly as double-clicking the launcher does.

Offered by the launcher at the end of its first-run setup, which runs
``python -m pyflashgui.core.shortcut``, and at any time from Tools > Settings.
Standard library only, since the launcher calls it before anything else of
pyflashgui's has been started.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Plain, since it starts whatever was last pulled. The installer's entries
#: carry the version they install, which is how the two are told apart.
NAME = "pyflashgui"
#: What each system calls the menu, for the Tools entry and the messages.
MENU = {"win32": "Start menu", "linux": "applications menu"}


def root() -> Path:
    """The folder the pyflashgui package sits in: the clone, for a source folder."""
    return Path(__file__).resolve().parent.parent.parent


def launcher(platform: str | None = None) -> Path | None:
    """The launcher to point the entry at, or None where there is no entry to make.

    None for a frozen build, which the installer looks after, for a pip
    installation, which has no launcher beside it, and on macOS, whose menu
    is not made of files like these.
    """
    platform = sys.platform if platform is None else platform
    if getattr(sys, "frozen", False) or platform not in MENU:
        return None
    script = root() / ("pyflashgui.cmd" if platform == "win32" else "pyflashgui.sh")
    return script if script.is_file() else None


def menu_name(platform: str | None = None) -> str:
    return MENU.get(sys.platform if platform is None else platform, "menu")


def entry_path(platform: str | None = None, environ=None) -> Path:
    """Where the entry goes: the user's own menu, so no administrator is asked."""
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    if platform == "win32":
        programs = Path(environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return programs / f"{NAME}.lnk"
    data = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "applications" / f"{NAME}.desktop"


def _desktop_quoted(path: Path) -> str:
    """A path as an Exec argument: quoted, with the characters the spec reserves escaped."""
    text = str(path)
    for reserved in ("\\", '"', "`", "$"):
        text = text.replace(reserved, "\\" + reserved)
    return f'"{text}"'


def desktop_entry(script: Path) -> str:
    """The .desktop file for a launcher.

    Run in a terminal: the first start after a pull may install libraries, and
    anything that goes wrong is said there, as it is when started by hand.
    """
    folder = script.parent
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Comment=Flash programming tool\n"
        f"Exec={_desktop_quoted(script)}\n"
        f"Path={folder}\n"
        f"Icon={folder / 'pyflashgui' / 'resources' / 'pyflashgui.png'}\n"
        "Terminal=true\n"
        "Categories=Development;Electronics;\n"
    )


def _windows_link(link: Path, script: Path) -> None:
    """Make the .lnk through the shell's own COM object, by way of PowerShell.

    The paths go in the environment rather than the command line, so no
    folder name can be mistaken for PowerShell syntax.
    """
    folder = script.parent
    command = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PYFLASHGUI_LINK);"
        "$s.TargetPath = $env:PYFLASHGUI_TARGET;"
        "$s.WorkingDirectory = $env:PYFLASHGUI_FOLDER;"
        "$s.IconLocation = $env:PYFLASHGUI_ICON;"
        "$s.Description = 'Flash programming tool, started from ' + $env:PYFLASHGUI_FOLDER;"
        "$s.Save()"
    )
    environ = dict(
        os.environ,
        PYFLASHGUI_LINK=str(link),
        PYFLASHGUI_TARGET=str(script),
        PYFLASHGUI_FOLDER=str(folder),
        PYFLASHGUI_ICON=str(folder / "pyflashgui" / "resources" / "pyflashgui.ico"),
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environ,
        capture_output=True,
        text=True,
        # pyflashgui runs under pythonw, and a console would flash up otherwise.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0 or not link.is_file():
        raise OSError(done.stderr.strip() or "PowerShell could not make the shortcut.")


def create(platform: str | None = None, environ=None) -> Path:
    """Make or replace the entry, and say where it is. OSError if it cannot be."""
    platform = sys.platform if platform is None else platform
    script = launcher(platform)
    if script is None:
        raise OSError("Only a source folder with its launcher needs a menu entry made.")
    path = entry_path(platform, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform == "win32":
        _windows_link(path, script)
    else:
        path.write_text(desktop_entry(script), encoding="utf-8")
        # Some desktops start only an entry that is marked executable.
        path.chmod(0o755)
    return path


def main() -> int:
    try:
        path = create()
    except OSError as exc:
        print(f" Could not add pyflashgui to the {menu_name()}: {exc}")
        return 1
    print(f" Added pyflashgui to the {menu_name()}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
