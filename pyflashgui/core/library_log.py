# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What pyOCD and pylink say for themselves, kept for Help > Diagnostics.

Both write to Python's logging rather than raising everything they have to
say: a probe that would not let go when disconnecting, a flash routine that
reported a fault, the parts of the debug port found on connecting. With no
handler of their own those lines went to a console pyflashgui started with
pythonw does not have, and were lost.

So the last of them are kept, from information up, for the diagnostics
report -- which is where the question "what did pyOCD make of this target?"
is answered -- and errors are passed to the Event Log as they happen.
Warnings are only kept: pyOCD gives several on an ordinary connection to
some targets, and an Event Log that opens itself for those would soon be
closed and not opened again.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

from pyflashgui.core.events import EventLog

#: The loggers listened to, and what each library is called when it is named.
LIBRARIES = {"pyocd": "pyOCD", "pylink": "pylink"}
#: How many lines are kept for the report.
KEPT = 100


def library_of(logger_name: str) -> str:
    """The library a logger belongs to, as it is written: pyocd.coresight.ap is pyOCD."""
    return LIBRARIES.get(logger_name.split(".")[0], logger_name)


def text_of(record: logging.LogRecord) -> str:
    """The line a record says, with the exception it carries where it adds anything."""
    try:
        text = record.getMessage()
    except Exception:  # a library's own mistake in its format string
        text = str(record.msg)
    if record.exc_info and (exc := record.exc_info[1]) is not None:
        said = str(exc).strip() or type(exc).__name__
        if said not in text:
            text = f"{text.rstrip(':')}: {said}" if text else said
    return text.strip()


class LibraryLog(logging.Handler):
    """Keeps what the libraries said, and passes their errors to the Event Log.

    Called on whichever thread the library was on -- usually the worker
    talking to the probe -- which is safe for both: a deque appends from any
    thread, and the Event Log crosses to the window's thread itself.
    """

    def __init__(self, events: EventLog, kept: int = KEPT) -> None:
        super().__init__(logging.INFO)
        self.events = events
        #: (time, level, library, text), oldest first.
        self.recent: deque[tuple[str, str, str, str]] = deque(maxlen=kept)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            library, text = library_of(record.name), text_of(record)
            self.recent.append(
                (f"{datetime.now():%H:%M:%S}", record.levelname.lower(), library, text)
            )
            if record.levelno >= logging.ERROR:
                self.events.error(f"{library}: {text}")
        except Exception:
            # Nothing a library says may stop it doing what it was doing, and
            # a handler that fails would be reported through logging again.
            pass

    def lines(self) -> list[str]:
        return [f"{when} {library} {level}: {text}" for when, level, library, text in self.recent]

    def install(self) -> None:
        """Listen to the libraries, from information up.

        Their loggers are left at information once set there: one handler
        removed and another added, as when a workspace is opened in a new
        window, must not leave the next listening to less.
        """
        for name in LIBRARIES:
            logger = logging.getLogger(name)
            if logger.getEffectiveLevel() > logging.INFO:
                logger.setLevel(logging.INFO)
            logger.addHandler(self)

    def remove(self) -> None:
        for name in LIBRARIES:
            logging.getLogger(name).removeHandler(self)
