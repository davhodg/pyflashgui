# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""One offscreen QApplication for the whole test session, and a drain between
tests.

The drain matters more than it looks. Windows and workers are created per
test and talk to each other through Qt signals, some of them emitted from
worker threads and so *queued*. If a queued signal is still in the event
queue when the test ends and its target is garbage collected, Qt delivers it
to a dead C++ object and the interpreter dies with a segmentation fault (an
access violation on Windows) somewhere in a later test.

Draining the queue while everything is still alive, then collecting garbage
before the next test starts, keeps that from happening.
"""

import gc
import os
import weakref

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

#: Taken before anything patches it, so a test that wants a real dialog can
#: have one back.
_REAL_EXEC = {QDialog: QDialog.exec, QMessageBox: QMessageBox.exec}


@pytest.fixture(scope="session", autouse=True)
def _isolate_settings(tmp_path_factory):
    """Keep QSettings in a temporary file rather than the registry.

    MainWindow saves its geometry and dock layout in closeEvent, so without
    this a test run leaves settings behind, and the next run restores a layout
    from the last one -- which is exactly what a layout test must not see.
    """
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings"))
    )


@pytest.fixture(autouse=True)
def _fresh_backends(monkeypatch):
    """A backend is made once and kept, and the simulated one remembers what
    was programmed into it: each test gets its own, with empty boards."""
    from pyflashgui import backends

    monkeypatch.setattr(backends, "_made", {})


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_unanswered_dialogs(monkeypatch):
    """A modal dialog nobody answered blocks forever.

    Offscreen or not, ``exec`` runs its own event loop and waits, so a test
    that reaches an unexpected dialog does not fail -- it hangs, which is the
    worst thing in a suite to work out. This turns that into an ordinary
    failure naming the dialog. A test that means to answer one patches
    ``exec`` itself, and its patch replaces this one.
    """

    def refuse(self, *_args, **_kwargs):
        raise AssertionError(
            f"a modal {type(self).__name__} opened that no test answered: {self.windowTitle()!r}"
        )

    for widget in (QDialog, QMessageBox):
        monkeypatch.setattr(widget, "exec", refuse)


@pytest.fixture
def real_dialogs(monkeypatch):
    """Put ``exec`` back, for the few tests that mean to open a real dialog.

    A test checking what happens *while* one is up has to have a real one, and
    arranges to close it itself.
    """
    for widget in (QDialog, QMessageBox):
        monkeypatch.setattr(widget, "exec", _REAL_EXEC[widget])


#: Background threads a test started, kept weakly so registering one here
#: never keeps it alive. See ``_drain_qt_events`` for what is done with them.
_THREADS: weakref.WeakSet = weakref.WeakSet()


def _still_going(thread) -> bool:
    """Whether this thread is running, asked in whichever way it answers.

    A ``QThread`` has ``isRunning``; anything else is asked for ``stopped``.
    Stopping one that has already stopped is not harmless: ``Worker.stop``
    disconnects a signal, and PySide warns loudly when there is nothing left
    to disconnect, which would fill the run with warnings about tests that
    tidied up properly.
    """
    try:
        if (running := getattr(thread, "isRunning", None)) is not None:
            return bool(running())
        return not getattr(thread, "stopped", False)
    except RuntimeError:  # the C++ side has gone, so nothing is running
        return False


def _watch(cls, monkeypatch):
    """Note every instance of ``cls`` a test makes, for stopping afterwards."""
    original = cls.__init__

    def made(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _THREADS.add(self)

    monkeypatch.setattr(cls, "__init__", made)


@pytest.fixture(autouse=True)
def _drain_qt_events(monkeypatch):
    from pyflashgui.core.worker import Worker

    _watch(Worker, monkeypatch)
    yield
    # Nothing a test started may outlive it. A QThread still running when Qt
    # destroys its C++ side aborts the process -- Worker.submit says the same
    # thing from the other end. Stopping them here rather than leaving it to
    # each test means a test that forgets is slow, not a crash in whatever ran
    # afterwards.
    for thread in list(_THREADS):
        if not _still_going(thread):
            continue  # its owner stopped it, which is the normal case
        try:
            thread.stop()
        except Exception:  # half-built, or stopping twice
            pass
        if (wait := getattr(thread, "wait", None)) is not None:
            wait(2000)
    _THREADS.clear()
    # Fixtures tear down after this point, so deliver what is already queued
    # first, then let go of anything unreferenced before the next test.
    instance = QCoreApplication.instance()
    if instance is not None:
        for _ in range(3):
            instance.processEvents()
    # Everything, not only the young generations. Collecting generations 0
    # and 1 is much cheaper -- a full collect walks the session's QApplication
    # and every imported module, and cost 78s against 48s for the suite -- but
    # it leaves anything that survived two collections mid-test to Python's
    # own sweep, at an arbitrary later moment rather than here, where the
    # queue has just been drained and no background thread is running. Qt
    # objects freed at that arbitrary moment are what CI kept dying on.
    gc.collect()
    if instance is not None:
        instance.processEvents()
