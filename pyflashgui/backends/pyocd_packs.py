# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The CMSIS-Packs pyOCD gets most of its targets from.

pyOCD has a few dozen targets built in. Every other Cortex-M device is
described by a CMSIS-Pack, which whoever makes the device publishes: its
memory, and the code that programs its flash. pyOCD finds a pack through an
index of all of them, downloads it once, and keeps it in a folder of the
user's -- the same folder its own ``pyocd pack`` command uses, so a pack
installed with either is there for both.

This is that command's work, for a window to ask for: an installed copy of
pyflashgui has no command line to type it at.

**Every call here blocks**, and fetching the index or a pack does so for as
long as the download takes. They are for a thread other than the window's.

Nothing here imports Qt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pyflashgui.backends.base import BackendError

#: Called as a download goes: how many files have arrived, and how many
#: there are, or None while that is not known yet.
Tick = Callable[[int, int | None], None]

#: More matches than this is a name too short to be looking for one device.
MOST_FOUND = 500

NO_LIST = (
    "The list of devices has not been fetched yet. Update the list first: it is what says "
    "which pack a device is in."
)


class PackError(BackendError):
    """Something about a pack went wrong that the user can be told about."""


@dataclass(frozen=True)
class Pack:
    """One CMSIS-Pack, at the version the index has."""

    vendor: str
    name: str
    version: str
    #: Where it is downloaded from.
    url: str = ""

    @property
    def label(self) -> str:
        return f"{self.vendor}.{self.name}"

    def __str__(self) -> str:
        return f"{self.label} {self.version}"


@dataclass(frozen=True)
class Device:
    """One device in the index, and the pack that describes it."""

    name: str
    vendor: str
    pack: Pack
    installed: bool


def open_cache(tick: Tick | None = None) -> Any:
    """pyOCD's own store of packs. Replaced in the tests, which have no network."""
    import cmsis_pack_manager

    class Cache(cmsis_pack_manager.Cache):
        # Where the library would write its progress to a console.
        def _verbose_on_tick_fn(self, total, current):
            if tick is not None:
                tick(current, total or None)

    return Cache(tick is None, False)


def _reference(pack: Pack) -> Any:
    from cmsis_pack_manager import CmsisPackRef

    return CmsisPackRef(pack.vendor, pack.name, pack.version)


def _file(cache: Any, pack: Pack) -> Path:
    """Where the pack is once it is installed. Its being there is what installed means."""
    return Path(cache.data_path) / _reference(pack).get_pack_name()


def _pack_of(entry: dict) -> Pack:
    source = entry["from_pack"]
    return Pack(source["vendor"], source["pack"], source["version"], source.get("url", ""))


def _said(doing: str, exc: Exception) -> PackError:
    return PackError(f"{doing} failed: {exc}")


def folder() -> Path:
    """Where the index and the packs are kept."""
    return Path(open_cache().data_path)


def list_fetched() -> datetime | None:
    """When the list of devices was last fetched, or None if it never was."""
    try:
        return datetime.fromtimestamp(Path(open_cache().index_path).stat().st_mtime)
    except OSError:
        return None


def fetch_list(tick: Tick | None = None) -> int:
    """Download the index of every pack. Returns how many devices it has."""
    cache = open_cache(tick)
    try:
        cache.cache_descriptors()
    except Exception as exc:
        raise _said("Fetching the list of devices", exc) from exc
    count = len(open_cache().index)
    if not count:
        raise PackError(
            "Fetching the list of devices brought nothing back. It comes from the internet: "
            "check that this computer can reach it."
        )
    return count


def find(text: str) -> list[Device]:
    """The devices whose part number has ``text`` in it, in any case."""
    wanted = "".join(text.split()).lower()
    if not wanted:
        return []
    cache = open_cache()
    index = cache.index
    if not index:
        raise PackError(NO_LIST)
    found = []
    there: dict[Pack, bool] = {}
    for name in sorted(index, key=str.lower):
        if wanted not in name.lower():
            continue
        entry = index[name]
        pack = _pack_of(entry)
        if pack not in there:
            there[pack] = _file(cache, pack).is_file()
        vendor = str(entry.get("vendor", "")).split(":")[0]
        found.append(Device(entry.get("name", name), vendor, pack, there[pack]))
    return found


def installed() -> list[Pack]:
    """The packs that have been downloaded."""
    cache = open_cache()
    packs = {_pack_of(entry) for entry in cache.index.values()}
    return sorted(
        (pack for pack in packs if _file(cache, pack).is_file()),
        key=lambda pack: pack.label.lower(),
    )


def install(pack: Pack, tick: Tick | None = None) -> None:
    """Download one pack. Its devices are targets from then on."""
    cache = open_cache(tick)
    try:
        cache.download_pack_list([_reference(pack)])
    except Exception as exc:
        raise _said(f"Downloading {pack}", exc) from exc
    # A download that did not arrive is not always an error where it is made.
    if not _file(cache, pack).is_file():
        where = f" from {pack.url}" if pack.url else ""
        raise PackError(
            f"{pack} was not downloaded{where}. Check that this computer can reach the "
            "internet; if the pack has since been replaced by a newer one, update the list."
        )


def remove(pack: Pack) -> None:
    """Delete one downloaded pack. The list still has it, to install again."""
    try:
        _file(open_cache(), pack).unlink(missing_ok=True)
    except OSError as exc:
        raise _said(f"Removing {pack}", exc) from exc
