# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The ways pyflashgui has of reaching a probe, by name.

A backend is made when it is first asked for and kept, so that there is one
of each: the simulated one holds what has been programmed into it, and two
of them would be two different sets of boards.
"""

from __future__ import annotations

from pyflashgui.backends.base import Backend, BackendError

#: What a workspace uses when it has not said.
DEFAULT = "pyocd"

#: In the order they are offered.
NAMES = ("pyocd", "jlink", "simulated")

_made: dict[str, Backend] = {}


def get(name: str = DEFAULT) -> Backend:
    """The backend of this name. Imported here, and only when asked for."""
    if name not in _made:
        if name == "pyocd":
            from pyflashgui.backends.pyocd_backend import PyocdBackend

            _made[name] = PyocdBackend()
        elif name == "jlink":
            from pyflashgui.backends.jlink_backend import JLinkBackend

            _made[name] = JLinkBackend()
        elif name == "simulated":
            from pyflashgui.backends.simulated import SimulatedBackend

            _made[name] = SimulatedBackend()
        else:
            raise BackendError(f"There is no backend called {name}.")
    return _made[name]
