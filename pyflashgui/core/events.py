# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Everything the application has to say, and how much it matters.

Every line that reaches the Event Log comes through here, with a level. That
one change buys two things.

The first is that a failure cannot be lost. The Event Log is a pane like any
other and can be closed, and closing it must not mean "throw away anything
you were going to tell me" -- press Program with no probe connected, and the
button would simply do nothing. So a warning or an error opens the pane; a
plain note does not, so closing it still means what it should mean, which is
"stop chattering at me".

The second is that the appearance of a line is decided in one place rather
than at every call site, so how warnings and errors look is a change to the
sink and nowhere else.

Levels are strings rather than an enum on purpose: they are passed about as
plain text, and nothing has to be imported to name one.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

INFORMATION = "information"
WARNING = "warning"
ERROR = "error"
#: Something that was wrong is right again, or something worked: a board
#: verified, a probe came back. Not an escalation of anything -- it is the one
#: piece of news a log of failures otherwise never carries, and reading back
#: through red to find out whether a fault ever cleared is a poor way to
#: spend a morning.
GOOD = "good"

#: In the order they escalate, with GOOD off to the side. Anything
#: unrecognised is treated as information: a mistyped level must not be able
#: to make the pane spring open, nor to silently swallow the message.
LEVELS = (INFORMATION, GOOD, WARNING, ERROR)

#: The levels that mean something needs looking at.
PROBLEMS = (WARNING, ERROR)


class EventLog(QObject):
    """The one way in. What listens is somebody else's business."""

    posted = Signal(str, str)  # message, level

    def post(self, message: str, level: str = INFORMATION) -> None:
        # Emitted rather than called: messages arrive from worker threads --
        # a flash in progress, the exception hook -- and a Qt widget may
        # only be touched from the GUI thread. A queued signal is the crossing.
        self.posted.emit(str(message), level if level in LEVELS else INFORMATION)

    def information(self, message: str) -> None:
        """Something happened. Worth recording, not worth interrupting for."""
        self.post(message, INFORMATION)

    def warning(self, message: str) -> None:
        """What you asked for did not happen, or did not happen as asked."""
        self.post(message, WARNING)

    def error(self, message: str) -> None:
        """Something went wrong that nobody asked for."""
        self.post(message, ERROR)

    def good(self, message: str) -> None:
        """Something that was wrong is right again."""
        self.post(message, GOOD)
