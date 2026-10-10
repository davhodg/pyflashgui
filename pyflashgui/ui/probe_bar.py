# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The toolbar: which probe, which target, how fast, and Connect.

Across the top of the window rather than in a pane, because it is the one
thing every pane depends on and the one thing that should never be closed
or tabbed behind something else.

What is chosen here is kept in the workspace: the target and the speed are
facts about the product being worked on. So is the probe, by its serial
number, so that a bench with two probes on it connects to the same one each
morning.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QLabel, QPushButton, QToolBar

from pyflashgui import backends
from pyflashgui.backends.base import ProbeInfo, TargetInfo
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher
from pyflashgui.ui import fonts

BACKEND_KEY = "probe.backend"
PROBE_KEY = "probe.id"
TARGET_KEY = "probe.target"
FREQUENCY_KEY = "probe.frequency"

#: The debug clock, in hertz, with None for whatever the probe chooses. Slow
#: ones first: a long or untidy cable is the usual reason for needing one.
FREQUENCIES = (
    ("Probe's own", None),
    ("100 kHz", 100_000),
    ("400 kHz", 400_000),
    ("1 MHz", 1_000_000),
    ("4 MHz", 4_000_000),
    ("10 MHz", 10_000_000),
)

NO_PROBES = "No probe found"

BACKEND_TIP = (
    "What pyflashgui reaches the probe through. Simulated is a probe and a\n"
    "target that exist only in memory, for trying things with no hardware."
)
PROBE_TIP = "The debug probe to connect through. Refresh looks for them again."
TARGET_TIP = (
    "The device on the end of the probe. Type part of its name to find it.\n"
    "The memory map is checked against it before it is connected to."
)
FREQUENCY_TIP = (
    "How fast the probe clocks the debug port. Lower it if connecting is\n"
    "unreliable: a long cable, or a target running from a slow clock."
)
CONNECT_TIP = (
    "Attach the probe to the target. The target is stopped while it is\n"
    "connected, and runs again when it is disconnected or reset."
)


class ProbeBar(QToolBar):
    def __init__(self, flasher: Flasher, ctx: Context) -> None:
        super().__init__("Probe")
        self.setObjectName("probe_bar")  # needed for saveState/restoreState
        self.setMovable(False)
        self.flasher = flasher
        self.ctx = ctx
        #: True while the boxes are being filled, so that filling one is not
        #: taken for somebody choosing what it was filled with.
        self._loading = False

        self.backend = QComboBox()
        self.backend.setToolTip(BACKEND_TIP)
        for name in backends.NAMES:
            self.backend.addItem(backends.get(name).label, name)
        self.backend.setAccessibleName("Backend")

        self.probe = QComboBox()
        self.probe.setToolTip(PROBE_TIP)
        self.probe.setAccessibleName("Probe")
        self.probe.setMinimumWidth(fonts.width_for(self.probe, "M" * 22))
        self.refresh = QPushButton("Refresh")
        self.refresh.setToolTip("Look again for the probes that are plugged in.")

        # Editable: there are hundreds of targets, and typing three letters
        # of one is quicker than scrolling to it.
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.setInsertPolicy(QComboBox.NoInsert)
        self.target.setToolTip(TARGET_TIP)
        self.target.setAccessibleName("Target")
        self.target.setMinimumWidth(fonts.width_for(self.target, "M" * 16))
        completer = self.target.completer() or QCompleter(self.target.model(), self.target)
        # Anywhere in the name: a part is as often known by the end of its
        # number as by the start.
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.target.setCompleter(completer)

        self.frequency = QComboBox()
        self.frequency.setToolTip(FREQUENCY_TIP)
        self.frequency.setAccessibleName("Speed")
        for label, hertz in FREQUENCIES:
            self.frequency.addItem(label, hertz)

        self.button = QPushButton("Connect")
        self.button.setCheckable(True)
        self.button.setToolTip(CONNECT_TIP)

        for label, widget in (
            ("Through", self.backend),
            ("Probe", self.probe),
            (None, self.refresh),
            ("Target", self.target),
            ("Speed", self.frequency),
            (None, self.button),
        ):
            if label is not None:
                self.addWidget(QLabel(f" {label}: "))
            self.addWidget(widget)

        self._restore()
        self.backend.currentIndexChanged.connect(self._on_backend)
        self.probe.currentIndexChanged.connect(self._on_probe)
        self.refresh.clicked.connect(self.flasher.refresh_probes)
        self.target.currentTextChanged.connect(self._on_target)
        self.frequency.currentIndexChanged.connect(self._on_frequency)
        self.button.toggled.connect(self._on_toggled)
        flasher.probes_changed.connect(self._show_probes)
        flasher.targets_changed.connect(self._show_targets)
        flasher.connection_changed.connect(self._on_connection)
        flasher.busy_changed.connect(lambda _busy: self._enable())
        flasher.finished.connect(self._on_finished)
        self._enable()

    # --- what was chosen last time ---------------------------------------------------
    def _restore(self) -> None:
        self._loading = True
        index = self.backend.findData(self.ctx.settings.get(BACKEND_KEY, backends.DEFAULT))
        self.backend.setCurrentIndex(max(index, 0))
        saved = self.ctx.settings.get(FREQUENCY_KEY)
        self.frequency.setCurrentIndex(max(self.frequency.findData(saved), 0))
        # Shown straight away, before the list it belongs to has arrived:
        # listing the targets means loading the flashing library, and the
        # window should not wait for that to say what was chosen.
        self.target.setEditText(str(self.ctx.settings.get(TARGET_KEY, "")))
        self._loading = False

    def start(self) -> None:
        """Ask for the probes and the targets. Once the window is up."""
        name = self.backend.currentData()
        if name != self.flasher.backend.name:
            self.flasher.set_backend(name)  # which asks for both itself
        else:
            self.flasher.refresh_targets()
            self.flasher.refresh_probes()
        if target := self.chosen_target():
            self.flasher.set_target(target)

    # --- what is chosen now ----------------------------------------------------------
    def chosen_probe(self) -> str:
        return str(self.probe.currentData() or "")

    def chosen_target(self) -> str:
        return self.target.currentText().strip()

    def chosen_frequency(self) -> int | None:
        return self.frequency.currentData()

    # --- filling the boxes -----------------------------------------------------------
    def _show_probes(self, probes: list[ProbeInfo]) -> None:
        wanted = self.chosen_probe() or str(self.ctx.settings.get(PROBE_KEY, ""))
        self._loading = True
        self.probe.clear()
        for probe in probes:
            self.probe.addItem(f"{probe.description} ({probe.unique_id})", probe.unique_id)
        if not probes:
            self.probe.addItem(NO_PROBES, "")
        # The one used last time if it is here, and the first otherwise.
        self.probe.setCurrentIndex(max(self.probe.findData(wanted), 0))
        self._loading = False
        self._enable()

    def _show_targets(self, targets: list[TargetInfo]) -> None:
        wanted = self.chosen_target()
        self._loading = True
        self.target.clear()
        for target in targets:
            self.target.addItem(target.name)
            if target.vendor:
                self.target.setItemData(
                    self.target.count() - 1, f"{target.vendor}, {target.source}", Qt.ToolTipRole
                )
        self.target.setEditText(wanted)
        self._loading = False
        self._enable()
        if wanted:
            self.flasher.set_target(wanted)

    # --- when something is chosen ----------------------------------------------------
    def _on_backend(self, _index: int) -> None:
        if self._loading:
            return
        name = self.backend.currentData()
        self.ctx.settings.set(BACKEND_KEY, name)
        self.flasher.set_backend(name)

    def _on_probe(self, _index: int) -> None:
        if not self._loading and self.chosen_probe():
            self.ctx.settings.set(PROBE_KEY, self.chosen_probe())
        self._enable()

    def _on_target(self, _text: str) -> None:
        if self._loading:
            return
        target = self.chosen_target()
        self.ctx.settings.set(TARGET_KEY, target)
        # Only for a name that is one: every letter typed on the way to it
        # is not a target to go and look up.
        if target and self.target.findText(target, Qt.MatchFixedString) >= 0:
            self.flasher.set_target(target)
        self._enable()

    def _on_frequency(self, _index: int) -> None:
        if not self._loading:
            self.ctx.settings.set(FREQUENCY_KEY, self.chosen_frequency())

    # --- connecting ------------------------------------------------------------------
    def _on_toggled(self, on: bool) -> None:
        if self._loading:
            return
        if on:
            self.flasher.connect_to(
                self.chosen_probe(), self.chosen_target(), self.chosen_frequency()
            )
        else:
            self.flasher.disconnect()
        self._enable()

    def _set_button(self, on: bool) -> None:
        """Put the button where things actually stand, without it being a press."""
        self._loading = True
        self.button.setChecked(on)
        self.button.setText("Disconnect" if on else "Connect")
        self._loading = False

    def _on_connection(self, connected: bool) -> None:
        self._set_button(connected)
        self._enable()

    def _on_finished(self, _name: str, _ok: bool) -> None:
        # A connect that failed leaves the button pressed and nothing
        # connected: back to what is true.
        self._set_button(self.flasher.connected)
        self._enable()

    def _enable(self) -> None:
        connected, busy = self.flasher.connected, self.flasher.busy
        for widget in (self.backend, self.probe, self.refresh, self.target, self.frequency):
            widget.setEnabled(not connected and not busy)
        can_connect = bool(self.chosen_probe() and self.chosen_target())
        self.button.setEnabled(not busy and (connected or can_connect))
