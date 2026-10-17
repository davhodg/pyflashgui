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

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QLabel,
    QPushButton,
    QToolBar,
)

from pyflashgui import backends
from pyflashgui.backends.base import ProbeInfo, TargetInfo
from pyflashgui.core.context import Context
from pyflashgui.core.flasher import Flasher
from pyflashgui.ui import fonts

BACKEND_KEY = "probe.backend"
PROBE_KEY = "probe.id"
TARGET_KEY = "probe.target"
FREQUENCY_KEY = "probe.frequency"
INTERFACE_KEY = "probe.interface"
STOP_KEY = "probe.stop"

#: The debug clock, in hertz, with None for whatever the probe chooses. Slow
#: ones first: a long or untidy cable is the usual reason for needing one.
FREQUENCIES = (
    ("Default", None),  # renamed per backend: see Backend.default_speed
    ("100 kHz", 100_000),
    ("400 kHz", 400_000),
    ("1 MHz", 1_000_000),
    ("4 MHz", 4_000_000),
    ("10 MHz", 10_000_000),
)

NO_PROBES = "No probe found"
LOOKING = "Looking for probes..."

BACKEND_TIP = (
    "What pyflashgui reaches the probe through. pyOCD works with many probes\n"
    "and Cortex-M devices. J-Link Commander works with a J-Link and every\n"
    "device SEGGER's software knows, and needs that software installed.\n"
    "Simulated is a probe and a target that exist only in memory, for\n"
    "trying things with no hardware."
)
PROBE_TIP = "The debug probe to connect through. Refresh looks for them again."
TARGET_TIP = (
    "The device on the end of the probe. Type part of its name to find it.\n"
    "The memory map is checked against it before it is connected to.\n"
    "One that is not here may be in a pack: Tools > pyOCD device packs."
)
FREQUENCY_TIP = (
    "How fast the probe clocks the debug port. The first choice leaves it to\n"
    "what is under Using: pyOCD's is 1 MHz, which is safe and slow, and a\n"
    "J-Link through J-Link Commander finds its own. The Event Log says the\n"
    "speed on connecting. Lower it if connecting is unreliable: a long cable,\n"
    "or a target running from a slow clock."
)
INTERFACE_TIP = (
    "How the probe is wired to the device's debug port. SWD is the two-wire\n"
    "one most Cortex-M boards bring out; the device's documentation says\n"
    "which it has."
)
CONNECT_TIP = (
    "Attach the probe to the target. The target is stopped on connecting\n"
    "-- through pyOCD, unless Stop when connecting is unticked -- and runs\n"
    "again when it is disconnected or reset."
)
STOP_TIP = (
    "Stop the target on connecting, as pyOCD does unless told otherwise.\n"
    "Untick to attach to it as it is, running: to read what a program is\n"
    "doing without stopping it. Erasing and programming stop it either way."
)


class ProbeBox(QComboBox):
    """The probe box, which says when it is about to open."""

    opening = Signal()

    def showPopup(self) -> None:
        self.opening.emit()
        super().showPopup()


class ProbeBar(QToolBar):
    def __init__(self, flasher: Flasher, ctx: Context) -> None:
        super().__init__("Probe")
        self.setObjectName("probe_bar")  # needed for saveState/restoreState
        self.setMovable(False)
        self.flasher = flasher
        self.ctx = ctx
        #: True while probes are being looked for.
        self._looking = False
        #: True while the boxes are being filled, so that filling one is not
        #: taken for somebody choosing what it was filled with.
        self._loading = False

        self.backend = QComboBox()
        self.backend.setToolTip(BACKEND_TIP)
        for name in backends.NAMES:
            self.backend.addItem(backends.get(name).label, name)
        self.backend.setAccessibleName("Backend")

        self.probe = ProbeBox()
        self.probe.setToolTip(PROBE_TIP)
        self.probe.setAccessibleName("Probe")
        self.probe.setMinimumWidth(fonts.width_for(self.probe, "M" * 22))
        self.refresh = QPushButton("Find probes")
        self.refresh.setToolTip(
            "Look again for the probes that are plugged in: for one plugged in\n"
            "since pyflashgui started. Opening the list looks again by itself\n"
            "when no probe was found."
        )

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

        # Only for a backend that can be told: the others choose, and a
        # box that does nothing is a box somebody will set and wonder about.
        self.interface = QComboBox()
        self.interface.setToolTip(INTERFACE_TIP)
        self.interface.setAccessibleName("Interface")

        self.button = QPushButton("Connect")
        self.button.setCheckable(True)
        self.button.setToolTip(CONNECT_TIP)
        #: Only where the backend can do otherwise: see _show_interfaces.
        self.stop = QCheckBox("Stop when connecting")
        self.stop.setToolTip(STOP_TIP)

        for label, widget in (
            ("Using", self.backend),
            ("Probe", self.probe),
            (None, self.refresh),
            ("Target", self.target),
            ("Speed", self.frequency),
        ):
            if label is not None:
                self.addWidget(QLabel(f" {label}: "))
            self.addWidget(widget)
        # Kept as actions, which is what a toolbar can show and hide.
        self._interface_label = self.addWidget(QLabel(" Interface: "))
        self._interface_action = self.addWidget(self.interface)
        self._stop_action = self.addWidget(self.stop)
        self.addWidget(self.button)

        self._restore()
        self.backend.currentIndexChanged.connect(self._on_backend)
        self.probe.currentIndexChanged.connect(self._on_probe)
        self.refresh.clicked.connect(self.flasher.refresh_probes)
        self.probe.opening.connect(self._on_probe_list_opening)
        self.target.currentTextChanged.connect(self._on_target)
        self.frequency.currentIndexChanged.connect(self._on_frequency)
        self.interface.currentIndexChanged.connect(self._on_interface)
        self.stop.toggled.connect(self._on_stop)
        self.button.toggled.connect(self._on_toggled)
        flasher.probes_changed.connect(self._show_probes)
        flasher.looking_for_probes.connect(self._on_looking)
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
        self.stop.setChecked(str(self.ctx.settings.get(STOP_KEY, True)).lower() != "false")
        # Shown straight away, before the list it belongs to has arrived:
        # listing the targets means loading the flashing library, and the
        # window should not wait for that to say what was chosen.
        self.target.setEditText(str(self.ctx.settings.get(TARGET_KEY, "")))
        self._loading = False
        self._show_interfaces()

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

    def choose_target(self, name: str) -> None:
        """Make ``name`` the target, as typing it would."""
        self.target.setEditText(name)

    def chosen_frequency(self) -> int | None:
        return self.frequency.currentData()

    def chosen_interface(self) -> str | None:
        return self.interface.currentText() or None

    def chosen_stop(self) -> bool:
        """Whether to stop the target on connecting: always, where the backend cannot not."""
        return self.stop.isChecked() or not backends.get(self.backend.currentData()).can_attach

    def _show_interfaces(self) -> None:
        """The interfaces the chosen backend can be asked for, or no box at all.

        And what leaving the speed to it comes to, which differs: pyOCD's is
        a slow and safe 1 MHz, and a J-Link finds its own.
        """
        backend = backends.get(self.backend.currentData())
        self.frequency.setItemText(0, backend.default_speed)
        offered = backend.interfaces
        self._loading = True
        self.interface.clear()
        self.interface.addItems(offered)
        saved = str(self.ctx.settings.get(INTERFACE_KEY, ""))
        self.interface.setCurrentIndex(max(self.interface.findText(saved), 0))
        self._loading = False
        for action in (self._interface_label, self._interface_action):
            action.setVisible(bool(offered))
        self._stop_action.setVisible(backend.can_attach)

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

    def _on_looking(self, looking: bool) -> None:
        """Say that probes are being looked for: through pyOCD it takes a
        second or two, and a list that changes with no warning looks broken."""
        self._looking = looking
        self.refresh.setText("Looking..." if looking else "Find probes")
        # An empty list says so; one with probes in keeps them to choose from.
        if looking and not self.chosen_probe():
            self._loading = True
            self.probe.clear()
            self.probe.addItem(LOOKING, "")
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
        # Each backend names targets its own way -- pyOCD's xmc4500-f100x1024
        # is J-Link's XMC4500-1024 -- so the one chosen for the last does not
        # carry over. Each keeps its own, for switching back.
        self.ctx.settings.set(f"{TARGET_KEY}.{self.flasher.backend.name}", self.chosen_target())
        wanted = str(self.ctx.settings.get(f"{TARGET_KEY}.{name}", ""))
        self._loading = True
        self.target.clear()  # the last backend's list; the new one's is on its way
        self.target.setEditText(wanted)
        self._loading = False
        self.ctx.settings.set(TARGET_KEY, wanted)
        self._show_interfaces()
        self.flasher.set_backend(name)

    def _on_probe_list_opening(self) -> None:
        """Look again when there was nothing to choose. Not otherwise: the answer
        takes a moment, and a list that changes under the mouse is worse than
        one a button brings up to date."""
        if not self.chosen_probe() and not self.flasher.busy:
            self.flasher.refresh_probes()

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

    def _on_interface(self, _index: int) -> None:
        if not self._loading and self.chosen_interface():
            self.ctx.settings.set(INTERFACE_KEY, self.chosen_interface())

    def _on_stop(self, on: bool) -> None:
        if not self._loading:
            self.ctx.settings.set(STOP_KEY, on)

    def _on_frequency(self, _index: int) -> None:
        if not self._loading:
            self.ctx.settings.set(FREQUENCY_KEY, self.chosen_frequency())

    # --- connecting ------------------------------------------------------------------
    def _on_toggled(self, on: bool) -> None:
        if self._loading:
            return
        if on:
            self.flasher.connect_to(
                self.chosen_probe(),
                self.chosen_target(),
                self.chosen_frequency(),
                self.chosen_interface(),
                self.chosen_stop(),
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
        for widget in (
            self.backend,
            self.probe,
            self.refresh,
            self.target,
            self.frequency,
            self.interface,
            self.stop,
        ):
            widget.setEnabled(not connected and not busy)
        self.refresh.setEnabled(self.refresh.isEnabled() and not self._looking)
        can_connect = bool(self.chosen_probe() and self.chosen_target())
        self.button.setEnabled(not busy and (connected or can_connect))
