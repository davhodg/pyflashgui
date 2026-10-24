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

import contextlib
import time
from collections.abc import Sequence
from pathlib import Path

from pyflashgui.backends import pyocd_packs
from pyflashgui.backends.base import (
    ERASE_CHIP,
    ERASE_NONE,
    ERASE_SECTORS,
    RESET_CORE,
    RESET_DEFAULT,
    RESET_PIN,
    RESET_SYSTEM,
    Backend,
    BackendError,
    Connection,
    ProbeInfo,
    Progress,
    TargetInfo,
    _nothing,
)
from pyflashgui.core.images import Segment
from pyflashgui.core.memory_map import FLASH, GENERIC, OTHER, RAM, ROM, Region

#: What pyOCD's loader calls the two ways of erasing.
_CHIP_ERASE = {ERASE_SECTORS: "sector", ERASE_CHIP: "chip"}
#: pyflashgui's ways of resetting, as pyOCD's Target.ResetType names them.
_RESET_TYPES = {
    RESET_DEFAULT: "",
    RESET_PIN: "HARDWARE",
    RESET_SYSTEM: "SYSTEM",
    RESET_CORE: "CORE",
}


def _kind(region) -> str:
    """One of pyflashgui's kinds of memory, for one of pyOCD's regions."""
    if region.is_flash:
        return FLASH
    if region.is_ram:
        return RAM
    if region.is_rom:
        return ROM
    return OTHER


def regions_of(memory_map, generic: bool = False) -> list[Region]:
    """A pyOCD memory map as pyflashgui's own regions, lowest address first.

    ``generic`` for the map of a target that is no device in particular,
    whose regions are where memory may be and not what is there.
    """
    out = []
    for region in memory_map:
        alias = region.alias
        out.append(
            Region(
                name=region.name,
                start=region.start,
                length=region.length,
                kind=GENERIC if generic else _kind(region),
                # pyOCD's "blocksize" is what is erased at a time, for flash.
                sector_size=int(getattr(region, "blocksize", 0) or 0) if region.is_flash else 0,
                page_size=int(getattr(region, "page_size", 0) or 0) if region.is_flash else 0,
                # An alias is given as the region itself, or as its name.
                alias_of=getattr(alias, "name", alias) or "",
                # From the pack's flash routine, for a device from a pack.
                erased=int(getattr(region, "erased_byte_value", 0xFF)) if region.is_flash else 0xFF,
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


#: Said on connecting a J-Link through pyOCD where it cannot be told the device.
SLOW_JLINK = (
    "Through pyOCD, with no pack to give this device's core, reading and writing go a word "
    "at a time, and a megabyte takes minutes. J-Link Commander, under Using, is quicker for it."
)


def is_jlink(probe) -> bool:
    """Whether pyOCD reaches this probe as a J-Link, in its own mode."""
    try:
        from pyocd.probe.jlink_probe import JLinkProbe
    except Exception:  # pylink not installed, or the J-Link software not found
        return False
    return isinstance(probe, JLinkProbe)


def _stages(progress: Progress) -> Progress:
    """pyOCD's progress through programming, said as erasing and then programming.

    pyOCD erases every sector it is to write, then writes them, and reports
    each from 0 to 1 to the one callback: passed on as it is, the bar ran
    through Programming twice. Within a stage it only ever goes forward, so
    going back is the next stage starting.
    """
    stages = iter(("Erasing", "Programming"))
    doing = next(stages)
    reached = 0.0

    def report(fraction: float) -> None:
        nonlocal doing, reached
        if fraction < reached:
            doing = next(stages, doing)
        reached = fraction
        progress(fraction, doing)

    return report


def _let_go(session) -> Exception | None:
    """Close a pyOCD session, and its probe even where closing the session fails.

    pyOCD's close lets go of the target before the probe, and when the
    first fails -- the board's power was turned off -- never closes the
    probe. A J-Link left open that way stays open: Find probes lists it, and
    every connect says "No emulator with serial number".
    Returns what went wrong, if anything did.
    """
    try:
        session.close()
        return None
    except Exception as exc:
        probe = getattr(session, "probe", None)
        if probe is not None and getattr(probe, "is_open", False):
            with contextlib.suppress(Exception):
                probe.close()
        return exc


def is_generic(target) -> bool:
    """Whether pyOCD knows this target as no device in particular: cortex_m.

    Its memory map is then the address map every Cortex-M has, made up on
    connecting, with no flash in it -- the region where a device's flash is
    called RAM. A device of its own is a subclass, with its own map.
    """
    try:
        from pyocd.coresight.coresight_target import CoreSightTarget
    except Exception:
        return False
    return type(target) is CoreSightTarget


def speed_text(hertz: int | None) -> str:
    """A debug clock as somebody would say it."""
    if not hertz:
        return ""
    if hertz % 1_000_000 == 0:
        return f"{hertz // 1_000_000} MHz"
    return f"{hertz / 1_000_000:g} MHz" if hertz >= 1_000_000 else f"{hertz // 1000} kHz"


#: Where every Cortex-M says which processor it is. Read after a reset to
#: find out whether the target still answers.
CPUID = 0xE000_ED00
#: How long to give a target after a reset before asking it, and then before
#: asking it again, each in turn. Never at once: a device starting up may not
#: answer -- an XMC4500 runs its own start-up code first -- and that is not a
#: lost connection.
SETTLE_S = (0.1, 0.2, 0.5, 1.0)
#: How long to wait before each attempt to connect again, when it was lost.
REATTACH_S = (0.2, 0.5, 1.0, 2.0)


class PyocdConnection(Connection):
    def __init__(self, session, reopen=None) -> None:
        self._session = session
        #: Makes a new session on the same probe and target, attaching to it
        #: as it is, for when a reset has taken the old one with it.
        self._reopen = reopen
        #: The options pyOCD was given, for Help > Diagnostics.
        self.options: dict = {}
        #: How many times a reset took the connection with it and it was made again.
        self.reattached = 0

    def details(self) -> list[str]:
        packs = self.options.get("pack") or []
        given = ", ".join(f"{k}={v}" for k, v in sorted(self.options.items()) if k != "pack")
        lines = [f"pyOCD options: {given or 'none'}"]
        if packs:
            lines.append(f"packs handed to pyOCD: {', '.join(Path(p).name for p in packs)}")
        if self.reattached:
            lines.append(f"connected again after a reset: {self.reattached} time(s)")
        session = self._session
        if session is None:
            return [*lines, "session: closed"]
        target, probe = getattr(session, "target", None), getattr(session, "probe", None)
        if target is not None:
            if is_generic(target):
                where = "no device in particular: the generic Cortex-M"
            elif "_pack_device" in vars(type(target)):
                where = "from a pack"
            else:
                where = "built in"
            lines.append(f"target class: {type(target).__name__}, {where}")
            for core in getattr(target, "cores", {}).values():
                architecture = getattr(getattr(core, "architecture", None), "name", "")
                lines.append(
                    f"core {getattr(core, 'core_number', '?')}: {getattr(core, 'name', '?')}"
                    + (f" ({architecture})" if architecture else "")
                )
        if probe is not None:
            wire = getattr(getattr(probe, "wire_protocol", None), "name", "") or "not known"
            lines.append(
                f"probe: {probe.description}; {type(probe).__name__}; "
                f"{probe.vendor_name or '?'} {probe.product_name or '?'}; wire protocol {wire}"
            )
        return lines

    def _target(self):
        if self._session is None:
            raise BackendError("This connection has been closed.")
        return self._session.target

    def regions(self) -> list[Region]:
        target = self._target()
        return regions_of(target.memory_map, generic=is_generic(target))

    def erase_chip(self) -> None:
        from pyocd.flash.eraser import FlashEraser

        self._from_reset()
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
        self._from_reset()
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
    ) -> str | None:
        from pyocd.flash.loader import MemoryLoader

        if erase not in _CHIP_ERASE and erase != ERASE_NONE:
            raise BackendError(f"There is no way of erasing called {erase!r}.")
        self._from_reset()
        if erase == ERASE_NONE:
            self._program_unerased(segments, progress)
            return None
        try:
            # smart_flash off: with it, pyOCD reads the flash first and
            # leaves alone a page it judges unchanged. Every byte in the file
            # is written here, and verifying afterwards says whether it took.
            loader = MemoryLoader(
                self._session,
                progress=_stages(progress),
                chip_erase=_CHIP_ERASE[erase],
                smart_flash=False,
            )
            for segment in segments:
                loader.add_data(segment.address, segment.data)
            loader.commit()
        except Exception as exc:
            raise _said("Programming", exc) from exc

    def _from_reset(self) -> None:
        """Reset the target and stop it at its first instruction, before a flash
        routine is run on it.

        pyOCD stops the processor wherever it happens to be and runs its
        routine there. Reported on an XMC4500 attached to its firmware as it
        ran: stopped amid the firmware, with its interrupts and the rest of
        what it had set up still on, the erase routine ended in a HardFault
        (IPSR=3). Reset first, the routine runs on a device as it starts,
        which is what flash routines are written for, and what SEGGER's own
        download does.
        """
        try:
            self._target().reset_and_halt()
        except BackendError:
            raise
        except Exception as exc:
            raise _said("Resetting the target before erasing or programming it", exc) from exc

    def _program_unerased(self, segments: Sequence[Segment], progress: Progress) -> None:
        """Write these bytes to flash erased beforehand, erasing nothing.

        pyOCD's own loader always erases first, so its flash builders are
        used directly: one for each region written to, given the bytes and
        told to program them. Bytes for RAM are written as they are.
        """
        target = self._target()
        builders: dict = {}
        total = sum(len(s) for s in segments) or 1
        written = 0
        try:
            for segment in segments:
                address, data = segment.address, bytes(segment.data)
                while data:
                    region = target.memory_map.get_region_for_address(address)
                    if region is None or not (region.is_flash or region.is_writable):
                        raise BackendError(f"{address:08X} cannot be written.")
                    # pyOCD's regions end at their last byte, not after it.
                    count = min(len(data), region.end - address + 1)
                    if not region.is_flash:
                        target.write_memory_block8(address, list(data[:count]))
                        written += count
                    else:
                        if region not in builders:
                            builders[region] = region.flash.get_flash_builder()
                        builders[region].add_data(address, data[:count])
                    data, address = data[count:], address + count
            for region in sorted(builders, key=lambda r: r.start):
                builder = builders[region]
                size, before = builder.buffered_data_size, written

                def report(fraction: float, size=size, before=before) -> None:
                    progress((before + fraction * size) / total)

                # keep_unwritten: the rest of a page written to is read and
                # written back as it is. Filled instead with what pyOCD takes
                # erased flash to read as, it would be written to: pyOCD
                # says FF for an XMC4500, whose erased flash reads 00.
                builder.program(progress_cb=report, smart_flash=False, keep_unwritten=True)
                written += size
        except BackendError:
            raise
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

    def reset(self, halt: bool = False, kind: str = RESET_DEFAULT) -> str | None:
        from pyocd.core.target import Target

        target = self._target()
        if kind not in _RESET_TYPES:
            raise BackendError(f"There is no way of resetting called {kind!r}.")
        # None is pyOCD's own choice: the session's, or the target's.
        reset_type = getattr(Target.ResetType, _RESET_TYPES[kind]) if _RESET_TYPES[kind] else None
        try:
            if halt:
                target.reset_and_halt(reset_type)
            else:
                target.reset(reset_type)
        except Exception as exc:
            raise _said("Resetting the target", exc) from exc
        if self._answers():
            return None
        self._reattach(halt)
        left = "stopped" if halt else "running"
        return (
            "The reset took the debug connection with it: connected again, leaving the "
            f"target {left}."
        )

    def _answers(self) -> bool:
        """Whether the target can still be reached, by reading which processor it is.

        Asked after a moment, then again a few times, a little later each
        time, before the answer is no: straight after a reset, a device may
        still be starting.
        """
        for wait in SETTLE_S:
            time.sleep(wait)
            try:
                self._target().read32(CPUID)
                return True
            except Exception:
                continue
        return False

    def _reattach(self, halt: bool) -> None:
        """Connect again, after a reset that took the debug connection with it.

        Reported on an XMC4500 through a J-Link: reset by its reset pin, the
        device reset its debug port as well, and the connection with it.
        pyflashgui still said connected, and every read after failed with
        "Unspecified error". Attached to as it is, so that what the
        reset started is left running.
        """
        if self._reopen is None:
            raise BackendError(
                "The target no longer answers since it was reset: disconnect, and connect again."
            )
        old, self._session = self._session, None
        _let_go(old)
        # Not at once, and not only once: reported failing with "Target is not
        # connected" when asked straight away, while the device was starting.
        failed: BackendError | None = None
        for wait in REATTACH_S:
            time.sleep(wait)
            try:
                self._session = self._reopen()
                self.reattached += 1
                break
            except BackendError as exc:
                failed = exc
        else:
            assert failed is not None
            raise BackendError(
                f"The reset took the debug connection with it, and connecting again failed: "
                f"{failed} Disconnect, and connect again."
            ) from failed
        if halt:
            try:
                self._target().halt()
            except Exception as exc:
                raise _said("Stopping the target after its reset", exc) from exc

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None and (failed := _let_go(session)) is not None:
            detail = str(failed).strip() or type(failed).__name__
            raise BackendError(
                f"Disconnecting failed: the probe did not answer ({detail}). It has been "
                "let go of anyway, so connecting again works once it answers. Was the "
                "board's power or the probe's USB cable taken away?"
            ) from failed


class PyocdBackend(Backend):
    # pyOCD's own, whatever the probe could do: 1 MHz, chosen to work with
    # a long or untidy cable, and slow for anything else.
    default_speed = "Default (1 MHz)"
    can_skip_erase = True
    can_attach = True
    reset_kinds = (RESET_DEFAULT, RESET_PIN, RESET_SYSTEM, RESET_CORE)
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

        # Once a pack's devices have been used, pyOCD lists them among its
        # own, spelt its way: "xmc4500_f100x1024" for the pack's
        # "xmc4500-f100x1024". Listed once, as from their pack, and not
        # again as built in.
        out = [
            TargetInfo(name, vendor=getattr(cls, "VENDOR", "") or "", source="built in")
            for name, cls in TARGET.items()
            if "_pack_device" not in vars(cls)
        ]
        seen = {pyocd_packs.same_name(t.name) for t in out}
        for device in self._file_devices():
            name = device.name.lower()
            if pyocd_packs.same_name(name) not in seen:
                seen.add(pyocd_packs.same_name(name))
                out.append(TargetInfo(name, vendor=device.vendor, source="pack file"))
        for device in self._pack_devices():
            name = device.part_number.lower()
            if pyocd_packs.same_name(name) not in seen:
                seen.add(pyocd_packs.same_name(name))
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
        stop: bool = True,
    ) -> Connection:
        from pyocd.core.helpers import ConnectHelper

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
            # pyOCD stops the target on connecting unless told to attach to
            # it as it is, running.
            "connect_mode": "halt" if stop else "attach",
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
        notes: list[str] = []
        if is_jlink(chosen):
            # Told the device, a J-Link reads and writes memory a block at a
            # time. Not told, pyOCD drives it a word at a time, each word a
            # round trip over USB: a megabyte took five minutes. A core's
            # name serves as the device's.
            try:
                core = pyocd_packs.core_of(target)
            except Exception:
                core = ""
            if core:
                options["jlink.device"] = core
            else:
                notes.append(SLOW_JLINK)
        try:
            session = self._open(chosen, options, target)
        except BackendError:
            if "jlink.device" not in options:
                raise
            # A name it does not take: connected without one, a word at a time.
            del options["jlink.device"]
            session = self._open(chosen, options, target)
            notes.append(SLOW_JLINK)
        # Attached to as it is: what a reset started is left running.
        again = {**options, "connect_mode": "attach"}
        connection = PyocdConnection(session, lambda: self._open(chosen, again, target))
        connection.speed = speed_text(session.options.get("frequency"))
        connection.notes = tuple(notes)
        connection.options = dict(options)
        return connection

    @staticmethod
    def _open(chosen, options: dict, target: str):
        from pyocd.core.session import Session

        session = None
        try:
            session = Session(chosen, auto_open=False, options=dict(options))
            session.open()
        except Exception as exc:
            # Let go of the probe whatever got as far as opening it: left
            # open, every later attempt fails on a probe that is in use, and
            # only switching backend and back -- which drops this one -- let
            # it go.
            if session is not None:
                _let_go(session)
            raise _said(f"Connecting to {target}", exc) from exc
        return session
