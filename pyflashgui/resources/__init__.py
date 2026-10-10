# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Data files shipped with pyflashgui (icons ...)."""

from importlib import resources
from pathlib import Path


def path(name: str) -> Path:
    return Path(str(resources.files(__name__) / name))
