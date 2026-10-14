# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Probes and targets through pyOCD.

Kept thin on purpose: each method is the pyOCD call that does it, with the
exception said again in pyflashgui's words. Anything worth testing without a
probe plugged in is in ``core`` or in the base class, and what is left here
can only be tried on hardware.

pyOCD is imported inside the methods that use it. It is the slowest thing
pyflashgui loads, and a window should not wait for it to say which probes
are plugged in before it can be drawn.
"""

from __future__ import annotations

from collections.abc import Sequence

from pyflashgui.backends import pyocd_packs
from pyflashgui.backends.base import (
    ERASE_CHIP,
    ERASE_SECTORS,
    Backend,
    BackendError,
    Connection,
    ProbeInfo,
    Progress,
    TargetInfo,
    _nothing,
)
from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import FLASH, OTHER, RAM, ROM, Region

#: What pyOCD's loader calls the two ways of erasing.
_CHIP_ERASE = {ERASE_SECTORS: "sector", ERASE_CHIP: "chip"}


def _kind(region) -> str:
    """One of pyflashgui's kinds of memory, for one of pyOCD's regions."""
    if region.is_flash:
        return FLASH
    if region.is_ram:
        return RAM
    if region.is_rom:
        return ROM
    return OTHER


def regions_of(memory_map) -> list[Region]:
    """A pyOCD memory map as pyflashgui's own regions, lowest address first."""
    out = []
    for region in memory_map:
        alias = region.alias
        out.append(
            Region(
                name=region.name,
                start=region.start,
                length=region.length,
                kind=_kind(region),
                # pyOCD's "blocksize" is what is erased at a time, for flash.
                sector_size=int(getattr(region, "blocksize", 0) or 0) if region.is_flash else 0,
                page_size=int(getattr(region, "page_size", 0) or 0) if region.is_flash else 0,
                # An alias is given as the region itself, or as its name.
                alias_of=getattr(alias, "name", alias) or "",
            )
        )
    return sorted(out, key=lambda r: r.start)


def needs_one_packet_at_a_time(*names: str | None) -> bool:
    """Whether a probe called this must be sent one command and then waited for.

    pyOCD's own advice for the TI XDS110, whose firmware loses track when
    several commands are outstanding. Set for every one of them, since it
    is not known which versions are free of it, and the cost is only speed.
    """
    return any("xds110" in (name or "").lower() for name in names)


def _said(doing: str, exc: Exception) -> BackendError:
    """A library's exception as a sentence about what was being attempted."""
    detail = str(exc).strip() or type(exc).__name__
    return BackendError(f"{doing} failed: {detail}")


class PyocdConnection(Connection):
    def __init__(self, session) -> None:
        self._session = session

    def _target(self):
        if self._session is None:
            raise BackendError("This connection has been closed.")
        return self._session.target

    def regions(self) -> list[Region]:
        return regions_of(self._target().memory_map)

    def erase_chip(self) -> None:
        from pyocd.flash.eraser import FlashEraser

        self._target()
        try:
            FlashEraser(self._session, FlashEraser.Mode.CHIP).erase()
        except Exception as exc:
            raise _said("Erasing the flash", exc) from exc

    def erase_ranges(self, ranges: Sequence[tuple[int, int]]) -> None:
        from pyocd.flash.eraser import FlashEraser

        flash = [r for r in self.regions() if r.kind == FLASH and not r.alias_of]
        for start, length in ranges:
            # Checked here: asked to erase what is not flash, pyOCD stops
            # with a line in its own log and no error, having erased
            # nothing, and that would be reported as done.
            if not any(r.start <= start and start + length <= r.end for r in flash):
                raise BackendError(
                    f"{start:08X} to {start + length - 1:08X} is not all within one "
                    "region of the target's flash."
                )
        try:
            # pyOCD takes where each range starts and where it stops.
            FlashEraser(self._session, FlashEraser.Mode.SECTOR).erase(
                [(start, start + length) for start, length in ranges]
            )
        except Exception as exc:
            raise _said("Erasing the flash", exc) from exc

    def program(
        self,
        segments: Sequence[Segment],
        erase: str = ERASE_SECTORS,
        progress: Progress = _nothing,
    ) -> None:
        from pyocd.flash.loader import MemoryLoader

        self._target()
        if erase not in _CHIP_ERASE:
            raise BackendError(f"There is no way of erasing called {erase!r}.")
        try:
            # smart_flash off: with it, pyOCD reads the flash first and
            # leaves alone a page it judges unchanged. Every byte in the file
            # is written here, and verifying afterwards says whether it took.
            loader = MemoryLoader(
                self._session,
                progress=progress,
                chip_erase=_CHIP_ERASE[erase],
                smart_flash=False,
            )
            for segment in segments:
                loader.add_data(segment.address, segment.data)
            loader.commit()
        except Exception as exc:
            raise _said("Programming", exc) from exc

    def read(self, address: int, length: int) -> bytes:
        target = self._target()
        try:
            return bytes(target.read_memory_block8(address, length))
        except Exception as exc:
            raise _said(f"Reading {length} bytes at {address:08X}", exc) from exc

    def write(self, address: int, data: bytes) -> None:
        target = self._target()
        try:
            target.write_memory_block8(address, list(data))
            # pyOCD may hold writes back to send together: these are sent now.
            target.flush()
        except Exception as exc:
            raise _said(f"Writing {len(data)} bytes at {address:08X}", exc) from exc

    def reset(self, halt: bool = False) -> None:
        target = self._target()
        try:
            if halt:
                target.reset_and_halt()
            else:
                target.reset()
        except Exception as exc:
            raise _said("Resetting the target", exc) from exc

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                raise _said("Disconnecting", exc) from exc


class PyocdBackend(Backend):
    name = "pyocd"
    label = "pyOCD"

    def probes(self) -> list[ProbeInfo]:
        from pyocd.core.helpers import ConnectHelper

        try:
            found = ConnectHelper.get_all_connected_probes(blocking=False)
        except Exception as exc:
            raise _said("Looking for probes", exc) from exc
        return [
            ProbeInfo(
                unique_id=probe.unique_id,
                description=probe.description,
                vendor=probe.vendor_name or "",
                product=probe.product_name or "",
            )
            for probe in found
        ]

    def targets(self) -> list[TargetInfo]:
        from pyocd.target import TARGET

        out = [
            TargetInfo(name, vendor=getattr(cls, "VENDOR", "") or "", source="built in")
            for name, cls in TARGET.items()
        ]
        seen = {t.name for t in out}
        for device in self._file_devices():
            name = device.name.lower()
            if name not in seen:
                seen.add(name)
                out.append(TargetInfo(name, vendor=device.vendor, source="pack file"))
        for device in self._pack_devices():
            name = device.part_number.lower()
            if name not in seen:
                seen.add(name)
                out.append(TargetInfo(name, vendor=device.vendor or "", source="pack"))
        return sorted(out, key=lambda t: t.name)

    @staticmethod
    def _pack_devices() -> list:
        """The devices in the CMSIS-Packs installed here. None is not a fault."""
        try:
            from pyocd.target.pack.pack_target import ManagedPacks

            return list(ManagedPacks.get_installed_targets())
        except Exception:
            # A pack index that is missing or damaged must not cost the
            # built-in targets, which need no pack at all.
            return []

    @staticmethod
    def _file_devices() -> list:
        """The devices in packs added from files. None is not a fault."""
        try:
            return pyocd_packs.file_devices()
        except Exception:
            return []

    def regions(self, target: str) -> list[Region]:
        from pyocd.target import TARGET

        cls = TARGET.get(target.lower())
        memory_map = getattr(cls, "MEMORY_MAP", None)
        # A built-in target carries its memory map on the class. A pack's is
        # read from the pack as the target is made, which needs a connection.
        return regions_of(memory_map) if memory_map is not None else []

    def connect(
        self,
        probe: str,
        target: str,
        frequency: int | None = None,
        interface: str | None = None,
    ) -> Connection:
        from pyocd.core.helpers import ConnectHelper
        from pyocd.core.session import Session

        try:
            found = ConnectHelper.get_all_connected_probes(blocking=False, unique_id=probe)
        except Exception as exc:
            raise _said("Looking for the probe", exc) from exc
        # Asked for by the whole id. pyOCD matches any id that *contains*
        # what it is given, and given two would ask on a console which was
        # meant -- a console pyflashgui does not have.
        chosen = next((p for p in found if p.unique_id == probe), None)
        if chosen is None:
            raise BackendError(f"The probe {probe} is not plugged in.")
        options: dict = {
            "target_override": target,
            # pyflashgui reports progress itself, through the callback.
            "hide_programming_progress": True,
        }
        if frequency is not None:
            options["frequency"] = int(frequency)
        # A device from a pack added from a file is one pyOCD knows nothing of
        # unless it is handed the pack.
        if packs := pyocd_packs.packs_for(target):
            options["pack"] = packs
        if needs_one_packet_at_a_time(chosen.description, chosen.product_name):
            options["cmsis_dap.limit_packets"] = True
        try:
            session = Session(chosen, auto_open=False, options=options)
            session.open()
        except Exception as exc:
            raise _said(f"Connecting to {target}", exc) from exc
        return PyocdConnection(session)
