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

A pack can also be added from a file, for a computer with no internet: one
downloaded by hand from its maker. That store only counts a pack that its
index lists, and a computer with no internet has no index, so such a pack is
kept in a folder of pyflashgui's own instead and handed to pyOCD by name
when one of its devices is connected to.

**Every call here blocks**, and fetching the index or a pack does so for as
long as the download takes. They are for a thread other than the window's.

Nothing here imports Qt.
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from pyflashgui.backends.base import BackendError
from pyflashgui.core import paths

#: Called as a download goes: how many files have arrived, and how many
#: there are, or None while that is not known yet.
Tick = Callable[[int, int | None], None]

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
    #: Where it is kept, for one added from a file rather than downloaded.
    file: str = ""

    @property
    def label(self) -> str:
        return f"{self.vendor}.{self.name}"

    @property
    def file_name(self) -> str:
        """What the pack file is called, wherever it is."""
        return f"{self.vendor}.{self.name}.{self.version}.pack"

    @property
    def address(self) -> str:
        """Where the pack file can be downloaded, by hand as well: its maker's
        folder, as the list gives it, and the file's name. Empty when the list
        does not say."""
        return f"{self.url.rstrip('/')}/{self.file_name}" if self.url else ""

    def __str__(self) -> str:
        return f"{self.label} {self.version}"


@dataclass(frozen=True)
class Device:
    """One device in the index, and the pack that describes it."""

    name: str
    vendor: str
    pack: Pack
    installed: bool


#: Called once, when fetching the list moves on from downloading to what
#: comes after: the library reads every description -- over fifteen hundred --
#: and writes the list of devices from them, twenty megabytes, which takes
#: half a minute or so with no count of its own to show.
Stage = Callable[[str], None]
PROCESSING = "Processing what was downloaded"


def open_cache(tick: Tick | None = None, stage: Stage | None = None) -> Any:
    """pyOCD's own store of packs. Replaced in the tests, which have no network."""
    import cmsis_pack_manager

    class Cache(cmsis_pack_manager.Cache):
        # Where the library would write its progress to a console.
        def _verbose_on_tick_fn(self, total, current):
            if tick is not None:
                tick(current, total or None)

        # The first thing the library does after the last download. Should a
        # later version of it name this otherwise, it is not called and the
        # step is not said: nothing else changes.
        def _call_rust_parse(self, pdsc_index):
            if stage is not None:
                stage(PROCESSING)
            return super()._call_rust_parse(pdsc_index)

    return Cache(tick is None, False)


#: The list of devices as last read, and the file it was read from and when
#: that was written: it is twenty megabytes of JSON, and the dialog asks for
#: it several times over each time it opens.
_read: tuple[str, float, dict] | None = None


def _index(cache: Any) -> dict:
    """The cache's list of devices, read again only when its file has changed."""
    global _read
    path = str(cache.index_path)
    try:
        written = Path(path).stat().st_mtime
    except OSError:
        return {}
    if _read is None or _read[:2] != (path, written):
        _read = (path, written, cache.index)
    return _read[2]


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


def fetch_list(tick: Tick | None = None, stage: Stage | None = None) -> int:
    """Download the index of every pack. Returns how many devices it has.

    ``stage`` is told when the downloads have ended and what they brought is
    processed, which is as long again.
    """
    cache = open_cache(tick, stage)
    try:
        cache.cache_descriptors()
    except Exception as exc:
        raise _said("Fetching the list of devices", exc) from exc
    # Through the copy kept of it, which the list of packs and the search
    # that follow then use rather than reading twenty megabytes again.
    count = len(_index(open_cache()))
    if not count:
        raise PackError(
            "Fetching the list of devices brought nothing back. It comes from the internet: "
            "check that this computer can reach it."
        )
    return count


def find(text: str) -> list[Device]:
    """The devices whose part number has ``text`` in it, in any case: all of them for none."""
    wanted = "".join(text.split()).lower()
    cache = open_cache()
    index = _index(cache)
    from_files = [d for d in file_devices() if wanted in d.name.lower()]
    if not index and not file_packs():
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
    # A device in a pack added from a file is installed, whatever the list says.
    names = {d.name.lower() for d in from_files}
    found = [d for d in found if d.name.lower() not in names] + from_files
    return sorted(found, key=lambda d: d.name.lower())


def installed() -> list[Pack]:
    """The packs that have been downloaded."""
    cache = open_cache()
    packs = {_pack_of(entry) for entry in _index(cache).values()}
    downloaded = [pack for pack in packs if _file(cache, pack).is_file()]
    return sorted(downloaded + file_packs(), key=lambda pack: pack.label.lower())


def install(pack: Pack, tick: Tick | None = None) -> None:
    """Download one pack. Its devices are targets from then on."""
    cache = open_cache(tick)
    try:
        cache.download_pack_list([_reference(pack)])
    except Exception as exc:
        raise _said(f"Downloading {pack}", exc) from exc
    # A download that did not arrive is not always an error where it is made.
    if not _file(cache, pack).is_file():
        where = f" from {pack.address}" if pack.address else ""
        raise PackError(
            f"{pack} was not downloaded{where}. Check that this computer can reach the "
            "internet; if the pack has since been replaced by a newer one, update the list."
        )


def remove(pack: Pack) -> None:
    """Delete one pack. A downloaded one is still in the list, to install again."""
    try:
        (Path(pack.file) if pack.file else _file(open_cache(), pack)).unlink(missing_ok=True)
    except OSError as exc:
        raise _said(f"Removing {pack}", exc) from exc


# --- packs from files -------------------------------------------------------------------
#: What each pack file was found to hold, by path, with when it was changed:
#: the list of targets asks every time it is filled, and reading a pack of
#: a whole family of devices is not instant.
_described: dict[str, tuple[float, Pack, tuple[tuple[str, str], ...]]] = {}


def files_folder() -> Path:
    """Where packs added from files are kept."""
    return paths.user_dir() / "packs"


def read_pack(path: Path) -> tuple[Pack, tuple[tuple[str, str], ...]]:
    """Which pack a .pack file is, and its devices as (part number, maker)."""
    from xml.etree import ElementTree

    # By the way in pyOCD's own modules take, before the part of it wanted
    # here: its modules are written to be imported from the top, and the
    # backend may be importing it on another thread at the same moment.
    import pyocd.target  # noqa: F401
    from pyocd.target.pack.cmsis_pack import CmsisPack

    try:
        with zipfile.ZipFile(path) as archive:
            # The description is at the top of the archive, beside its folders.
            described = [n for n in archive.namelist() if n.lower().endswith(".pdsc")]
            if not described:
                raise PackError(
                    f"{path.name} is not a CMSIS-Pack: there is no description (.pdsc) in it."
                )
            root = ElementTree.fromstring(archive.read(min(described, key=lambda n: n.count("/"))))
            # Read through this archive, which is closed after, so the file can
            # be removed again: Windows will not delete an open file.
            found = {
                (d.part_number, (d.vendor or "").split(":")[0]) for d in CmsisPack(archive).devices
            }
    except PackError:
        raise
    except Exception as exc:
        raise PackError(f"{path.name} cannot be read as a CMSIS-Pack: {exc}") from exc
    release = root.find("releases/release")
    vendor, name = root.findtext("vendor"), root.findtext("name")
    version = release.get("version") if release is not None else None
    if not (vendor and name and version):
        raise PackError(
            f"{path.name} does not say which pack it is: it has no vendor, name or version."
        )
    if not found:
        raise PackError(f"{path.name} describes no devices, so there would be nothing to choose.")
    return Pack(vendor.strip(), name.strip(), version.strip()), tuple(sorted(found))


def _described_file(path: Path) -> tuple[Pack, tuple[tuple[str, str], ...]] | None:
    try:
        changed = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    if (kept := _described.get(key)) is None or kept[0] != changed:
        try:
            pack, devices = read_pack(path)
        except PackError:
            return None  # one that has gone bad is left out, not the end of the list
        kept = _described[key] = (changed, replace(pack, file=key), devices)
    return kept[1], kept[2]


def file_packs() -> list[Pack]:
    """The packs added from files."""
    return [d[0] for d in map(_described_file, sorted(files_folder().glob("*.pack"))) if d]


def file_devices() -> list[Device]:
    """The devices in the packs added from files."""
    out = []
    for path in sorted(files_folder().glob("*.pack")):
        if (described := _described_file(path)) is not None:
            pack, devices = described
            out += [Device(name, maker, pack, True) for name, maker in devices]
    return out


def report() -> list[str]:
    """For Help > Diagnostics: where the packs are, which there are, and how
    old the list of devices is. Found from the files, without reading the
    list itself, which is twenty megabytes."""
    where = folder()
    fetched = list_fetched()
    lines = [
        f"folder: {where}",
        f"list of devices fetched {fetched:%Y-%m-%d %H:%M}" if fetched else "list never fetched",
    ]
    downloaded = sorted(p.relative_to(where).as_posix() for p in where.rglob("*.pack"))
    lines += [f"installed: {name}" for name in downloaded] or ["none installed"]
    lines += [f"added from a file: {p.name}" for p in sorted(files_folder().glob("*.pack"))]
    return lines


def same_name(part: str) -> str:
    """A device's name as pyOCD files it, whichever way it is spelt.

    pyOCD adds the devices of the packs it has to its own list of targets
    as "xmc4500_f100x1024", and the pack calls it "XMC4500-F100x1024": both
    are one device, and are looked up as one.
    """
    import pyocd.target

    return pyocd.target.normalise_target_type_name(part)


def packs_for(target: str) -> list[str]:
    """The pack files with this device in, for pyOCD to be handed when connecting."""
    wanted = same_name(target)
    return [d.pack.file for d in file_devices() if same_name(d.name) == wanted]


def add_file(source: str) -> tuple[Pack, int]:
    """Keep a copy of a .pack file, and say which pack it is and how many devices it has."""
    pack, devices = read_pack(Path(source))
    folder = files_folder()
    kept = folder / f"{pack.vendor}.{pack.name}.{pack.version}.pack"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        # The same pack at another version is replaced rather than kept beside it:
        # two descriptions of one device would leave pyOCD to pick one.
        for older in folder.glob(f"{pack.vendor}.{pack.name}.*.pack"):
            if older != kept:
                older.unlink()
        if Path(source).resolve() != kept.resolve():
            shutil.copyfile(source, kept)
    except OSError as exc:
        raise _said(f"Adding {Path(source).name}", exc) from exc
    return replace(pack, file=str(kept)), len(devices)


# --- what a pack says about a device ----------------------------------------------------
def _core(device: Any) -> str:
    """A pack device's core, as the pack names it: "Cortex-M4". Empty if it does not say."""
    for element in getattr(getattr(device, "_info", None), "processors", None) or []:
        if core := element.attrib.get("Dcore", ""):
            return core
    return next((name for name in device.processors_map if name.startswith("Cortex-M")), "")


def core_of(target: str) -> str:
    """The core of a device from an installed pack, or empty for one from no pack.

    Read from the packs added from files and from pyOCD's own, whichever has it.
    """
    import pyocd.target  # noqa: F401  # see read_pack
    from pyocd.target.pack.cmsis_pack import CmsisPack

    wanted = same_name(target)
    for path in packs_for(target):
        with zipfile.ZipFile(path) as archive:
            for device in CmsisPack(archive).devices:
                if same_name(device.part_number) == wanted and (core := _core(device)):
                    return core
    from pyocd.target.pack.pack_target import ManagedPacks

    for device in ManagedPacks.get_installed_targets():
        if same_name(device.part_number) == wanted and (core := _core(device)):
            return core
    return ""
