# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Where the machine's own things live.

The settings and the layout live in a workspace -- see ``core/workspaces.py``
-- because they are about the product being worked on rather than about this
computer. What is here is the folder the workspaces all sit under.

Windows:  %APPDATA%\\pyflashgui        (e.g. C:\\Users\\you\\AppData\\Roaming\\pyflashgui)
Linux:    $XDG_CONFIG_HOME/pyflashgui  (default ~/.config/pyflashgui)
macOS:    ~/Library/Application Support/pyflashgui

Set ``PYFLASHGUI_HOME`` to override (used by the tests).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pyflashgui import APP_NAME


def made(path: Path) -> Path:
    """The folder, made if it is not there. Asked about before it is made.

    ``mkdir(exist_ok=True)`` is one call and looks cheaper than a question
    followed by a call, and on a local disc it is. On a profile redirected
    to a network share, or one a scanner is watching, creating a directory
    is the expensive operation and asking whether it exists is not: half a
    second went on two of these at startup on such a machine, and these
    functions are called all over the place.
    """
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir() -> Path:
    if override := os.environ.get("PYFLASHGUI_HOME"):
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    return made(base)
