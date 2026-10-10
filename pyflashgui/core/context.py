# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What the panes are handed: where things live, and where to say things.

Keep this small and stable: everything a pane needs to remember something or
to tell the user something should be reachable from ``ctx``.
"""

from __future__ import annotations

from pathlib import Path

from pyflashgui.core import paths, timing, workspaces
from pyflashgui.core.events import EventLog
from pyflashgui.core.layout import Layout
from pyflashgui.core.settings import Settings


class Context:
    def __init__(self, events: EventLog | None = None) -> None:
        # Marked in three because the whole of it is folders being made and
        # two files being read, which costs nothing on a local disc and a
        # surprising amount on a profile that is redirected to a network
        # share or watched by a scanner.
        self.user_dir: Path = paths.user_dir()
        timing.mark("user folder")
        #: Which product is being worked on. Everything below belongs to it.
        self.workspace: str = workspaces.active()
        self.workspace_dir: Path = workspaces.active_dir()
        timing.mark("workspace folders")
        self.settings = Settings(workspaces.settings_path())
        #: The dock arrangement, in the workspace folder rather than in
        #: QSettings, so that the workspace is one thing that can be copied.
        self.layout = Layout(workspaces.layout_path())
        timing.mark("settings and layout files")
        #: Everything said to the user goes through here, with a level.
        self.events = events if events is not None else EventLog()
