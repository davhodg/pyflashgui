# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""What the user has agreed to before pyflashgui changes a target.

**Once a session, per thing.**  Erasing and programming replace what a device
holds, and cannot be undone. Each asks before the first time, and then stays
out of the way -- a dialog on every board would be worse than useless,
because it would be dismissed unread.

The unit of "once" is the *key*, which spells out what was agreed to. Keying
the question on the target is deliberate: saying yes to programming one part
is not saying yes to another, and the wrong part chosen is exactly the
mistake the question is there to catch.

It offers to be remembered, and what "remembered" means is the interesting
part. An answer is kept **against the person who gave it, on the machine they
gave it on**, in ``QSettings`` -- never in the workspace. A workspace is a
folder made to be copied, backed up and handed to someone else, and an agreement
that travelled inside one would mean somebody else's window, on somebody else's
bench, quietly not asking. The user name is stored alongside and checked, so
that a settings store which does somehow arrive on another machine, or under
another account, asks that person for themselves.
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

#: Kept outside every workspace, deliberately. See the module docstring.
AGREED_SETTING = "confirmations/agreed"
USER_SETTING = "confirmations/user"

REMEMBER_LABEL = "Do not ask me this again on this machine"
REMEMBER_TIP = (
    "Kept for you, on this computer, outside any workspace -- so it does not\n"
    "travel in a workspace handed to somebody else, and another account on\n"
    "this machine is asked for itself.\n\n"
    "Tools > Reset > Re-enable all confirmations brings them back."
)


def _who() -> str:
    """The account this is being agreed by, or "" where that cannot be told."""
    try:
        return getpass.getuser()
    except Exception:  # no password database, no USERNAME: not worth failing over
        return ""


class Remembered:
    """Agreements kept between sessions, for one person on one machine.

    A thin wrapper over ``QSettings`` rather than a store of our own, because
    ``QSettings`` is already per user by construction -- the registry under
    HKEY_CURRENT_USER on Windows, the account's own config directory
    elsewhere -- which is most of what is wanted here. The user name is
    written alongside and checked on the way out, so that the one case
    ``QSettings`` does not cover, a store copied somewhere else, is covered
    too: it asks that person for themselves rather than assuming the answer
    somebody else gave.
    """

    def __init__(self, settings: QSettings | None = None, user: str | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()
        self._user = _who() if user is None else user

    def keys(self) -> set[str]:
        if self._settings.value(USER_SETTING, "") != self._user:
            return set()  # somebody else's answers, which are not ours to use
        stored = self._settings.value(AGREED_SETTING, [])
        if isinstance(stored, str):  # a one-item list comes back as a string
            stored = [stored]
        return {str(key) for key in stored or []}

    def add(self, key: str) -> None:
        self._settings.setValue(USER_SETTING, self._user)
        self._settings.setValue(AGREED_SETTING, sorted(self.keys() | {key}))

    def clear(self) -> int:
        """Forget everything, so every question comes back. Returns how many."""
        how_many = len(self.keys())
        for name in (AGREED_SETTING, USER_SETTING):
            self._settings.remove(name)
        return how_many


class Confirmations:
    """Which questions have been answered yes, this session or for good.

    ``remembered`` is what makes an answer outlive the session, and it is
    optional so that anything constructing one of these for a test, or for a
    pane of its own, gets the session-only behaviour rather than reaching into
    the real user's settings by accident.
    """

    def __init__(self, remembered: Remembered | None = None) -> None:
        self._store = remembered
        self._agreed: set[str] = set(remembered.keys()) if remembered is not None else set()

    def agreed(self, key: str) -> bool:
        return key in self._agreed

    def ask(self, parent: QWidget | None, key: str, title: str, text: str) -> bool:
        """Ask, unless this exact key has already been agreed to.

        Defaults to Cancel: these dialogs appear in the middle of doing
        something else, and the safe answer should be the one you get by
        pressing return without reading carefully.

        The tick box is offered only where there is somewhere to keep the
        answer. Offering it and then forgetting at the end of the session
        would be a promise the dialog could not keep.

        The question is the dialog's text, not only its title: a title bar is
        the part of a dialog least read, and a question kept there would
        leave Yes and Cancel under an explanation of something nobody had
        asked.
        """
        if key in self._agreed:
            return True
        box = QMessageBox(
            QMessageBox.Warning, title, title, QMessageBox.Yes | QMessageBox.Cancel, parent
        )
        box.setInformativeText(text)
        box.setDefaultButton(QMessageBox.Cancel)
        again = None
        if self._store is not None:
            again = QCheckBox(REMEMBER_LABEL)
            again.setToolTip(REMEMBER_TIP)
            box.setCheckBox(again)
        if box.exec() != QMessageBox.Yes:
            return False
        self._agreed.add(key)
        if again is not None and again.isChecked():
            self._store.add(key)
        return True

    def allow(self, key: str) -> None:
        """Record agreement without asking, for a case that carries no risk."""
        self._agreed.add(key)

    def forget(self, key: str | None = None) -> None:
        """Ask again this session. What was remembered for good is untouched."""
        if key is None:
            self._agreed.clear()
        else:
            self._agreed.discard(key)

    def forget_everything(self) -> int:
        """Ask again, including the answers that were being kept for good."""
        self._agreed.clear()
        return self._store.clear() if self._store is not None else 0
