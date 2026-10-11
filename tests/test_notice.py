# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""The notice shown at every start, and the loading that goes on behind it."""

import threading
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QProgressDialog

from pyflashgui.ui import confirm
from pyflashgui.ui.confirm import accept_notice


def test_continuing_past_the_notice_starts_pyflashgui(app, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        QMessageBox, "exec", lambda box: seen.update(text=box.informativeText()) or QMessageBox.Ok
    )
    assert accept_notice()
    assert seen["text"] == confirm.NOTICE
    assert "cannot be undone" in seen["text"] and "without warranty" in seen["text"]


def test_quitting_the_notice_means_it_does_not_start(app, monkeypatch):
    """A click-through nobody can decline is not an agreement."""
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Cancel)
    assert not accept_notice()


def test_it_cannot_be_switched_off(app, monkeypatch):
    """The one dialog here with no "do not ask again" on it."""
    seen = []
    monkeypatch.setattr(
        QMessageBox, "exec", lambda box: seen.append(box.checkBox()) or QMessageBox.Ok
    )
    assert accept_notice()
    assert accept_notice()
    assert seen == [None, None], "no tick box, and shown again the next time"


def test_the_slow_half_of_starting_up_happens_behind_it(app, monkeypatch):
    order = []
    monkeypatch.setattr(
        QMessageBox, "exec", lambda _box: order.append("answered") or QMessageBox.Ok
    )
    assert accept_notice(while_shown=lambda: order.append("loaded"))
    assert sorted(order) == ["answered", "loaded"]


def test_the_notice_can_be_answered_while_it_is_still_loading(app, monkeypatch):
    release = threading.Event()
    answered_while_loading = []

    def answer(_box):
        answered_while_loading.append(not release.is_set())
        release.set()
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "exec", answer)
    finished = []
    assert accept_notice(while_shown=lambda: (release.wait(5), finished.append(1)))
    assert answered_while_loading == [True]
    assert finished == [1], "and it had finished loading by the time it returned"


def test_continue_before_the_loading_is_done_shows_it_is_still_going(app, monkeypatch):
    release = threading.Event()
    shown = []
    real_show = QProgressDialog.show

    def show(dialog):
        shown.append(dialog)
        release.set()
        return real_show(dialog)

    monkeypatch.setattr(QProgressDialog, "show", show)
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Ok)
    assert accept_notice(while_shown=lambda: release.wait(5))
    assert len(shown) == 1


def test_quit_does_not_wait_for_the_loading(app, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Cancel)
    assert not accept_notice(while_shown=lambda: release.wait(5))
    release.set()


def test_what_the_loading_raises_is_raised_to_whoever_asked(app, monkeypatch):
    import pytest

    def fail():
        raise RuntimeError("a library would not load")

    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Ok)
    with pytest.raises(RuntimeError, match="would not load"):
        accept_notice(while_shown=fail)


def test_the_readme_says_what_the_notice_says():
    """One wording, so that the two cannot come to disagree."""
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Safety notice", 1)[1].split("\n## ", 1)[0]
    for paragraph in confirm.NOTICE.split("\n\n")[:-1]:
        assert paragraph in section


def test_starting_shows_the_notice_first_and_quit_ends_it_there(app, monkeypatch):
    import pyflashgui.__main__ as entry

    asked = []
    monkeypatch.setattr(entry.sys, "argv", ["pyflashgui"])
    monkeypatch.setattr(QMessageBox, "exec", lambda box: asked.append(box) or QMessageBox.Cancel)
    assert entry.main() == 0
    assert len(asked) == 1
