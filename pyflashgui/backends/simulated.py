# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""A probe and a target that exist only in memory.

For the tests, which cannot have a board plugged in, and for working on
pyflashgui at a desk with no hardware on it. It behaves as flash does where
that matters to what is built on it: erased flash reads as FF, a sector is
erased whole, and bytes can only be put where the target has memory.

What is programmed stays for as long as the backend object does, so that a
second connection to the same probe finds what the first one wrote -- as a
board keeps its flash between one connection and the next.
"""

from __future__ import annotations

from collections.abc import Sequence

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
from pyflashgui.core.memory_map import FLASH, RAM, Region, region_at

ERASED = 0xFF

PROBES = (
    ProbeInfo("SIM0001", "Simulated probe 1", vendor="pyflashgui", product="Simulated probe"),
    ProbeInfo("SIM0002", "Simulated probe 2", vendor="pyflashgui", product="Simulated probe"),
)

#: The targets, and the memory of each. Sizes chosen to be awkward in the
#: ways real parts are: one with a single flash, one with two that do not
#: touch and have different sector sizes.
TARGETS: dict[str, tuple[Region, ...]] = {
    "sim_single": (
        Region("flash", 0x0800_0000, 0x4_0000, FLASH, sector_size=0x1000, page_size=0x100),
        Region("ram", 0x2000_0000, 0x1_0000, RAM),
    ),
    "sim_dual": (
        Region("boot", 0x0000_0000, 0x8000, FLASH, sector_size=0x400, page_size=0x100),
        Region("application", 0x1000_0000, 0x10_0000, FLASH, sector_size=0x1000, page_size=0x100),
        Region(
            "application_mirror",
            0x1100_0000,
            0x10_0000,
            "rom",
            alias_of="application",
        ),
        Region("ram", 0x2000_0000, 0x2_0000, RAM),
    ),
}


class _Board:
    """What is on the end of one simulated probe: a target and its memory."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.regions = TARGETS[target]
        self.memory = {
            r.name: bytearray([ERASED if r.kind == FLASH else 0]) * r.length
            for r in self.regions
            if not r.alias_of
        }
        self.resets = 0
        #: How each reset was asked for, in order.
        self.reset_kinds: list[str] = []

    def storage(self, region: Region) -> bytearray:
        """The bytes behind a region, which for an alias are another's."""
        return self.memory[region.alias_of or region.name]


class SimulatedConnection(Connection):
    def __init__(self, backend: SimulatedBackend, probe: str, board: _Board) -> None:
        self._backend = backend
        self._probe = probe
        self._board: _Board | None = board

    def _open(self) -> _Board:
        if self._board is None:
            raise BackendError("This connection has been closed.")
        return self._board

    def regions(self) -> list[Region]:
        return list(self._open().regions)

    def erase_chip(self) -> None:
        board = self._open()
        for region in board.regions:
            if region.kind == FLASH and not region.alias_of:
                board.memory[region.name][:] = bytes([ERASED]) * region.length

    def erase_ranges(self, ranges: Sequence[tuple[int, int]]) -> None:
        board = self._open()
        # Everything is placed before anything is erased, so that a range
        # that is not flash leaves the target as it was.
        placed = [self._place(board, start, length) for start, length in ranges]
        for runs in placed:
            for region, _offset, _length in runs:
                if region.kind != FLASH:
                    raise BackendError(f"{region.name} is not flash, and cannot be erased.")
        for runs in placed:
            for region, offset, length in runs:
                size = region.sector_size
                start = offset // size * size
                stop = -(-(offset + length) // size) * size
                board.memory[region.name][start:stop] = bytes([ERASED]) * (stop - start)

    def _place(self, board: _Board, address: int, length: int) -> list[tuple[Region, int, int]]:
        """A run of bytes as (region, offset in it, length), region by region."""
        out = []
        end = address + length
        while address < end:
            region = region_at(board.regions, address)
            if region is None:
                raise BackendError(f"The target has no memory at {address:08X}.")
            if region.alias_of or region.kind not in (FLASH, RAM):
                raise BackendError(f"{address:08X} is in {region.name}, which cannot be written.")
            stop = min(end, region.end)
            out.append((region, address - region.start, stop - address))
            address = stop
        return out

    def program(
        self,
        segments: Sequence[Segment],
        erase: str = ERASE_SECTORS,
        progress: Progress = _nothing,
    ) -> None:
        board = self._open()
        if erase not in (ERASE_SECTORS, ERASE_CHIP, ERASE_NONE):
            raise BackendError(f"There is no way of erasing called {erase!r}.")
        # Everything is placed before anything is changed, so that a file
        # that does not fit leaves the target as it was.
        placed = [(s, self._place(board, s.address, len(s))) for s in segments]
        if erase == ERASE_CHIP:
            self.erase_chip()
        elif erase == ERASE_SECTORS:
            for _segment, runs in placed:
                for region, offset, length in runs:
                    if region.kind != FLASH:
                        continue
                    size = region.sector_size
                    start = offset // size * size
                    stop = -(-(offset + length) // size) * size
                    board.memory[region.name][start:stop] = bytes([ERASED]) * (stop - start)
        total = sum(len(s) for s in segments)
        done = 0
        for segment, runs in placed:
            position = 0
            for region, offset, length in runs:
                data = segment.data[position : position + length]
                memory = board.memory[region.name]
                if region.kind == FLASH:
                    # As real flash: writing clears bits and never sets them,
                    # so over what is not blank it holds neither.
                    data = bytes(
                        a & b for a, b in zip(memory[offset : offset + length], data, strict=True)
                    )
                memory[offset : offset + length] = data
                position += length
                done += length
                progress(done / total)

    def read(self, address: int, length: int) -> bytes:
        board = self._open()
        out = bytearray()
        end = address + length
        while address < end:
            region = region_at(board.regions, address)
            if region is None:
                raise BackendError(f"The target has no memory at {address:08X}.")
            stop = min(end, region.end)
            offset = address - region.start
            out += board.storage(region)[offset : offset + stop - address]
            address = stop
        return bytes(out)

    def write(self, address: int, data: bytes) -> None:
        board = self._open()
        runs = self._place(board, address, len(data))
        for region, _offset, _length in runs:
            if region.kind == FLASH:
                raise BackendError(f"{region.name} is flash: program it instead.")
        position = 0
        for region, offset, length in runs:
            board.memory[region.name][offset : offset + length] = data[position : position + length]
            position += length

    def reset(self, halt: bool = False, kind: str = RESET_DEFAULT) -> None:
        board = self._open()
        if kind not in SimulatedBackend.reset_kinds:
            raise BackendError(f"There is no way of resetting called {kind!r}.")
        board.resets += 1
        board.reset_kinds.append(kind)
        # What a reset does to RAM on a real part is nothing anybody should
        # rely on. Cleared here, so that relying on it shows up.
        for region in board.regions:
            if region.kind == RAM:
                board.memory[region.name][:] = bytes(region.length)

    def close(self) -> None:
        if self._board is not None:
            self._board = None
            self._backend._released(self._probe)


class SimulatedBackend(Backend):
    name = "simulated"
    label = "Simulated"
    can_skip_erase = True
    # Each the same here, but offered, so that choosing between them can be tried.
    reset_kinds = (RESET_DEFAULT, RESET_PIN, RESET_SYSTEM, RESET_CORE)

    def __init__(self) -> None:
        #: Probe id -> what it is attached to. Made when first connected to,
        #: and kept, so that flash outlives a connection.
        self._boards: dict[str, _Board] = {}
        self._in_use: set[str] = set()

    def probes(self) -> list[ProbeInfo]:
        return list(PROBES)

    def targets(self) -> list[TargetInfo]:
        return [TargetInfo(name, vendor="pyflashgui", source="built in") for name in TARGETS]

    def regions(self, target: str) -> list[Region]:
        return list(TARGETS.get(target, ()))

    def connect(
        self,
        probe: str,
        target: str,
        frequency: int | None = None,
        interface: str | None = None,
        stop: bool = True,
    ) -> Connection:
        if probe not in {p.unique_id for p in PROBES}:
            raise BackendError(f"There is no probe with the id {probe}.")
        if target not in TARGETS:
            raise BackendError(f"{target} is not a target the simulated backend has.")
        if probe in self._in_use:
            raise BackendError(f"Probe {probe} is already connected.")
        board = self._boards.get(probe)
        if board is None or board.target != target:
            # A different target on the same probe is a different board
            # plugged in, with nothing of the last one's on it.
            board = self._boards[probe] = _Board(target)
        self._in_use.add(probe)
        return SimulatedConnection(self, probe, board)

    def _released(self, probe: str) -> None:
        self._in_use.discard(probe)

    def board(self, probe: str) -> _Board | None:
        """What is on the end of a probe, for a test to look at or tamper with."""
        return self._boards.get(probe)
