# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The Python Console pane: a prompt, and Run script..., with ``flash`` to hand.

Built on the standard library's ``code.InteractiveConsole``, so it behaves
like the ``python`` prompt: blocks over several lines, ``...`` to carry on
one, and Python's own tracebacks. The box typed into takes several lines as
well -- Shift+Enter for another, or several pasted at once -- and Enter then
runs them together, as one block. What is printed is shown as it is printed,
so a script that programs ten boards says so one board at a time.

Code runs on the window's own thread, which is what lets it touch the window
and the panes. ``flash`` calls wait for the probe with the window still
going, and ``wait(seconds)`` is a script's sleep for the same reason: while
either is waiting, Stop is pressed, and stops the script at that point.
"""

from __future__ import annotations

import ast
import code
import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pyflashgui.core.context import Context
from pyflashgui.ui import folders, fonts
from pyflashgui.ui.scripting import Flash, ScriptError, ScriptStoppedError

BANNER = """pyflashgui console -- Python {version}
  flash     the probe and the target: connect(), read(address, length),
            write(address, data), erase(), program("app.hex"), verify(),
            reset(). Each waits for its answer.
  files     the Files pane       window    the main window
  log(text) a line in the Event Log
  wait(s)   let the window run for s seconds: a script's sleep
Shift+Enter for another line, or paste several: Enter runs them together.
Type help(flash) to see everything it does."""

RUN_TIP = (
    "Run a Python file here, with the same names this console has:\n"
    "flash, files, window, log and wait."
)
STOP_TIP = (
    "Stop the script, or the line typed, at the next thing it asks of\n"
    "the probe or the next wait. What the probe is doing now is\n"
    "cancelled if it can be: a read or a verify can, programming cannot."
)
#: The most lines the box typed into grows to before it scrolls.
TALLEST = 10
#: What Tab puts in, and what a line after a colon is indented by.
INDENT = "    "
#: How much the pane keeps, in lines. A script printing in a loop for an
#: hour must not take the memory with it.
MOST_LINES = 5000


def _said(kind, value) -> str | None:
    """How an error from ``flash`` is shown: as a sentence, not a traceback."""
    if issubclass(kind, ScriptStoppedError):
        return "Stopped.\n"
    if issubclass(kind, ScriptError):
        return f"ScriptError: {value}\n"
    return None


class _Console(code.InteractiveConsole):
    """An interactive console whose errors are shown in it, as Python shows them.

    The standard one hands an error to ``sys.excepthook`` whenever a program
    has replaced it, and pyflashgui has: its hook reports what escapes its
    own code as a fault in pyflashgui. A mistake in what was typed is the
    typist's, and belongs under the line that made it.
    """

    def showtraceback(self) -> None:
        kind, value, tb = sys.exc_info()
        if (said := _said(kind, value)) is not None:
            self.write(said)
            return
        # The first entry is this console's own call into the typed code.
        self.write("".join(traceback.format_exception(kind, value, tb.tb_next if tb else None)))

    def showsyntaxerror(self, filename=None, **_kwargs) -> None:
        kind, value, _tb = sys.exc_info()
        self.write("".join(traceback.format_exception_only(kind, value)))

    def write(self, data: str) -> None:
        sys.stderr.write(data)


class _Shown(io.TextIOBase):
    """Printed text, into the pane as it is printed."""

    def __init__(self, view: ConsoleView) -> None:
        super().__init__()
        self._view = view

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._view.write(text)
        return len(text)


class _Typed(QPlainTextEdit):
    """What is typed: a line, or several, with Up and Down going through what
    was typed before.

    Enter is the end of it, and says so with ``entered``; Shift+Enter
    is another line, indented as the one before and further after a colon.
    One line tall until there is more, so that it looks like the prompt it
    mostly is.
    """

    entered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []
        self._pos = 0
        self._draft = ""
        self.setWordWrapMode(QTextOption.NoWrap)
        self.setTabChangesFocus(False)
        self.textChanged.connect(self._fit)
        self._fit()

    # Named as QLineEdit's are, which is what this was and what its callers use.
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        self.moveCursor(QTextCursor.End)

    def _fit(self) -> None:
        lines = min(max(self.document().blockCount(), 1), TALLEST)
        margins = self.contentsMargins()
        frame = 2 * int(self.document().documentMargin()) + margins.top() + margins.bottom()
        self.setFixedHeight(self.fontMetrics().lineSpacing() * lines + frame)

    def _new_line(self) -> None:
        """Another line, indented as this one, and further after a colon."""
        line = self.textCursor().block().text()
        indent = line[: len(line) - len(line.lstrip())]
        if line.rstrip().endswith(":"):
            indent += INDENT
        self.insertPlainText("\n" + indent)

    def remember(self, line: str) -> None:
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
        self._pos = len(self.history)
        self._draft = ""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self._new_line()
            else:
                self.entered.emit()
            return
        if event.key() == Qt.Key_Tab:
            self.insertPlainText(INDENT)
            return
        cursor = self.textCursor()
        # Within what is typed, Up and Down move between its lines; only from
        # the first line, or the last, do they go through what came before.
        on_edge = (event.key() == Qt.Key_Up and cursor.blockNumber() == 0) or (
            event.key() == Qt.Key_Down and cursor.blockNumber() == self.document().blockCount() - 1
        )
        if event.key() in (Qt.Key_Up, Qt.Key_Down) and self.history and on_edge:
            if self._pos == len(self.history):
                self._draft = self.text()
            self._pos += -1 if event.key() == Qt.Key_Up else 1
            self._pos = max(0, min(self._pos, len(self.history)))
            self.setText(self.history[self._pos] if self._pos < len(self.history) else self._draft)
            return
        super().keyPressEvent(event)


class ConsoleView(QWidget):
    #: A file was run, by the button here or from the File menu: its path.
    ran = Signal(str)

    def __init__(self, namespace: dict, flash: Flash, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.flash = flash
        self.namespace = namespace
        self.console = _Console(namespace)
        #: True while a line or a script is running. Nothing else is taken
        #: until it has finished, and the window will not close under it.
        self.running = False
        mono = fonts.mono()

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(mono)
        self.output.setMaximumBlockCount(MOST_LINES)
        self.output.setAccessibleName("Console output")
        self.prompt = QLabel(">>>")
        self.prompt.setFont(mono)
        self.input = _Typed()
        self.input.setFont(mono)
        self.input.setAccessibleName("Python")
        self.input.entered.connect(self._on_enter)
        self.run_button = QPushButton("Run script...")
        self.run_button.setToolTip(RUN_TIP)
        self.run_button.clicked.connect(self._run_script_dialog)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip(STOP_TIP)
        self.stop_button.clicked.connect(self.stop)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.output.clear)

        row = QHBoxLayout()
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)
        row.addWidget(self.run_button)
        row.addWidget(self.stop_button)
        row.addWidget(clear)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.output)
        layout.addLayout(row)

        self.write(BANNER.format(version=sys.version.split()[0]) + "\n")
        self._enable()

    # --- running ---------------------------------------------------------------------
    def _on_enter(self) -> None:
        typed = self.input.text()
        self.input.clear()
        self.input.remember(typed)
        if "\n" not in typed:
            self.write(f"{self.prompt.text()} {typed}\n")
            more = self._run(lambda: self.console.push(typed))
            self.prompt.setText("..." if more else ">>>")
            return
        lines = typed.split("\n")
        first = self.prompt.text()
        self.write(
            "".join(f"{first if i == 0 else '...'} {line}\n" for i, line in enumerate(lines))
        )
        # What was begun a line at a time and finished with these.
        source = "\n".join([*self.console.buffer, *lines])
        self.console.resetbuffer()
        self._run(lambda: self._run_block(source))
        self.prompt.setText(">>>")

    def _run_block(self, source: str) -> None:
        """Several lines run as one, each value shown as the prompt shows it.

        Compiled as the prompt compiles one statement, but with all of them:
        "a = 2", "a * 3" shows 6, as typing them one at a time would.
        """
        try:
            tree = ast.parse(source, "<console>")
            compiled = compile(ast.Interactive(body=tree.body), "<console>", "single")
        except (SyntaxError, ValueError, OverflowError):
            self.console.showsyntaxerror("<console>")
            return
        self.console.runcode(compiled)

    def run_source(self, source: str, filename: str = "<script>") -> None:
        """Run a whole script with this console's names: what Run script... does."""
        self.write(f"--- running {filename}\n")

        def go() -> None:
            try:
                exec(compile(source, filename, "exec"), self.namespace)
            except SystemExit:
                print("(the script called exit, which here ends the script and nothing more)")
            except Exception:
                kind, value, tb = sys.exc_info()
                if (said := _said(kind, value)) is not None:
                    sys.stderr.write(said)
                else:
                    # The first entry is this function's own call into the script.
                    sys.stderr.write(
                        "".join(traceback.format_exception(kind, value, tb.tb_next if tb else None))
                    )

        self._run(go)
        self.write(f"--- {filename} has finished\n")

    def run_file(self, path: str) -> None:
        file = Path(path)
        try:
            source = file.read_text(encoding="utf-8")
        except OSError as exc:
            self.write(f"{file} cannot be read: {exc}\n")
            return
        # Before it runs: a script that fails is still the one to run again.
        self.ran.emit(str(file))
        self.run_source(source, str(file))

    def _run(self, work):
        """Run ``work`` with what it prints shown here, one at a time."""
        if self.running:
            return None
        self.running = True
        self.flash.started()
        self._enable()
        shown = _Shown(self)
        try:
            with redirect_stdout(shown), redirect_stderr(shown):
                return work()
        finally:
            self.running = False
            self._enable()
            self.input.setFocus()

    def stop(self) -> None:
        if self.running:
            self.flash.stop()

    def _run_script_dialog(self) -> None:
        path = folders.open_file(
            self, self.ctx, folders.SCRIPT, "Run Python script", "Python (*.py)", self.ctx.user_dir
        )
        if path:
            self.run_file(path)

    def _enable(self) -> None:
        self.input.setEnabled(not self.running)
        self.run_button.setEnabled(not self.running)
        self.stop_button.setEnabled(self.running)

    # --- output ----------------------------------------------------------------------
    def write(self, text: str) -> None:
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)
