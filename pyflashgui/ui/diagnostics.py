# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What Help > Diagnostics says beyond the versions, and its window.

The report answers "what is pyflashgui doing, and what did it ask of the
probe?" on the spot, and for a bug report afterwards. Above all it says how
the connection was made -- the backend, the options pyOCD was given, what it
made of the target -- what was done to the target and in what order, and
what pyOCD said for itself while doing it.

Each section is built on its own and a failure costs only that section: a
report that cannot be made because one part of the window is in an odd state
is no use at exactly the moment it is wanted. Every section says "nothing"
rather than being left out, so a missing line is never mistaken for an empty
one. Nothing here asks the probe anything: the worker may be using it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout, QWidget

from pyflashgui.backends import jlink_backend, pyocd_packs
from pyflashgui.core.flasher import size_text
from pyflashgui.core.memory_map import FLASH
from pyflashgui.ui import folders, fonts
from pyflashgui.ui.memory_view import ERASED_KEY

#: How many warnings and errors the window keeps for the report.
RECENT_PROBLEMS = 20


def _target(window) -> str:
    flasher = window.flasher
    return flasher.target if flasher.connected else window.probe_bar.chosen_target()


# --- the probe and the target ----------------------------------------------------------
def connection(window) -> list[str]:
    """What is chosen, what is connected, and how."""
    flasher, bar = window.flasher, window.probe_bar
    backend = flasher.backend
    target = _target(window)
    lines = [
        f"using {backend.label}; probe {bar.chosen_probe() or 'none chosen'}; "
        f"target {bar.chosen_target() or 'none chosen'}",
        f"speed {bar.frequency.currentText()}"
        + (f"; interface {bar.chosen_interface()}" if bar.chosen_interface() else "")
        + (
            f"; stop when connecting {'on' if bar.chosen_stop() else 'off'}"
            if backend.can_attach
            else ""
        ),
    ]
    if flasher.connected:
        at = f" at {flasher.connection.speed}" if flasher.connection.speed else ""
        lines.append(f"connected to {flasher.target} through probe {flasher.probe}{at}")
        lines += flasher.connection.details()
    else:
        lines.append("not connected")
    lines.append(f"busy: {flasher.doing or 'yes'}" if flasher.busy else "not busy")
    if target:
        if flasher.connected:
            lines.append(f"reset way chosen: {window.files_view.reset_kind()}")
        erased = window.ctx.settings.get(f"{ERASED_KEY}.{target}", None)
        if erased not in (None, ""):
            lines.append(f"erased flash chosen to read as {int(erased):02X}")
    return lines


def probes(window) -> list[str]:
    return [
        f"{probe.description} ({probe.unique_id})"
        + (f"; {probe.vendor} {probe.product}".rstrip() if probe.vendor or probe.product else "")
        for probe in window.flasher.probes_found
    ]


def memory_map(window) -> list[str]:
    """The target's memory as pyflashgui has it, and where what is ticked lands."""
    lines = []
    for region in window.flasher.regions:
        extra = [f"erased {region.erased:02X}"] if region.kind == FLASH else []
        if region.sector_size:
            extra.append(f"sectors {size_text(region.sector_size)}")
        if region.alias_of:
            extra.append(f"the same memory as {region.alias_of}")
        lines.append(
            f"{region.name}: {region.kind} {region.start:08X} to {region.end - 1:08X}, "
            f"{size_text(region.length)}" + (f"; {', '.join(extra)}" if extra else "")
        )
    if not lines:
        lines.append("no memory known for this target until connected")
    map_view = window.map_view
    lines.append(f"map says: {map_view.summary.text()}")
    if (made := getattr(map_view, "layout_shown", None)) is not None:
        lines += [f"{problem.level}: {problem.message}" for problem in made.problems]
    return lines


def files(window) -> list[str]:
    """Each entry in the Files pane, and the Memory panes open."""
    lines = []
    for entry in window.files_view.entries:
        image = entry.image
        what = (
            f"crop of {entry.cropped_from}"
            if entry.cropped_from
            else (f"read from {entry.target}" if entry.is_read else "file")
        )
        shape = (
            f"{image.format} {image.address:08X}, {size_text(image.size)}, "
            f"{len(image.segments)} segment(s)"
            if image is not None and image.segments
            else "not read"
        )
        notes = [
            note
            for note, wanted in (
                ("ticked" if entry.enabled else "not ticked", True),
                ("unsaved", entry.unsaved),
                (f"problem: {entry.problem}", bool(entry.problem)),
            )
            if wanted
        ]
        lines.append(f"{entry.name}: {what}; {shape}; {', '.join(notes)}")
    if titles := [window.panes.docks[n].windowTitle() for n in window._memory_panes()]:
        lines.append(f"Memory panes: {', '.join(titles)}")
    return lines


def operations(window) -> list[str]:
    return [operation.line() for operation in window.flasher.history]


def library_log(window) -> list[str]:
    return window.library_log.lines()


# --- what is installed alongside --------------------------------------------------------
def commander(_window) -> list[str]:
    return jlink_backend.report()


def packs(_window) -> list[str]:
    return pyocd_packs.report()


# --- what went wrong, and what is set ---------------------------------------------------
def problems(window) -> list[str]:
    return [
        f"{when} {level}: {text.splitlines()[0] if text else ''}"
        for when, level, text in window.recent_problems
    ]


def settings(window) -> list[str]:
    lines = [f"workspace: {window.ctx.workspace} ({window.ctx.workspace_dir})"]
    lines.append(f"script running: {'yes' if window.script_running() else 'no'}")
    agreed = window.confirm.described()
    lines += [f"not asking: {line}" for line in agreed] or ["every confirmation is asked"]
    return lines


def threads(_window) -> list[str]:
    return sorted(
        f"{thread.name}{' (daemon)' if thread.daemon else ''}" for thread in threading.enumerate()
    )


#: In the order the report gives them: the connection first.
SECTIONS: tuple[tuple[str, Callable], ...] = (
    ("Connection", connection),
    ("Probes found", probes),
    ("Memory map", memory_map),
    ("Files", files),
    ("Recent operations", operations),
    ("pyOCD and pylink log", library_log),
    (f"Last {RECENT_PROBLEMS} warnings and errors", problems),
    ("J-Link Commander", commander),
    ("pyOCD packs", packs),
    ("Workspace and confirmations", settings),
    ("Threads", threads),
)


def section(title: str, build: Callable, window) -> list[str]:
    """One section, whatever happens in building it."""
    try:
        body = build(window) or ["nothing"]
    except Exception as exc:  # one odd corner must not cost the whole report
        body = [f"could not be read: {type(exc).__name__}: {exc}"]
    return ["", title, *(f"  {line}" for line in body)]


def sections(window) -> list[str]:
    lines: list[str] = []
    for title, build in SECTIONS:
        lines += section(title, build, window)
    return lines


# --- the window ---------------------------------------------------------------------------
class DiagnosticsDialog(QDialog):
    """The report, to read, refresh, copy or save. One, brought forward when asked again."""

    def __init__(self, parent: QWidget, make: Callable[[], str], ctx) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.resize(860, 640)
        self._make = make
        self._ctx = ctx
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(fonts.mono())
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text.setAccessibleName("Diagnostics report")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        refresh = buttons.addButton("Refresh", QDialogButtonBox.ActionRole)
        refresh.setToolTip("Make the report again, as things are now.")
        refresh.clicked.connect(self.refresh)
        copy = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        copy.setToolTip("Put the whole report on the clipboard, for a bug report.")
        copy.clicked.connect(self.copy_to_clipboard)
        save = buttons.addButton("Save...", QDialogButtonBox.ActionRole)
        save.setToolTip("Write the report to a text file.")
        save.clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(buttons)
        self.refresh()

    def report(self) -> str:
        return self.text.toPlainText()

    def refresh(self) -> None:
        self.text.setPlainText(self._make())

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self.report())

    def save(self) -> None:
        path = folders.save_file(
            self,
            self._ctx,
            folders.EXPORT,
            "Save diagnostics",
            "Text (*.txt);;All files (*)",
            self._ctx.user_dir,
            suggested=folders.stamped("pyflashgui-diagnostics", ".txt"),
        )
        if not path:
            return
        try:
            Path(path).write_text(self.report() + "\n", encoding="utf-8")
        except OSError as exc:
            self._ctx.events.error(f"Could not write {path}: {exc}")
            return
        self._ctx.events.information(f"Diagnostics written to {path}")
