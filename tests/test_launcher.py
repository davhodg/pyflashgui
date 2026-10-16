# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Starting up: noticing a dependency that was added since .venv was built.

The launchers used to set up only when .venv was missing, so adding a library
broke every existing checkout. Under pythonw there is no console, so what the
user saw was a window that never opened and no message anywhere.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from pyflashgui.ui import messages

# build/ is not a package -- it holds the scripts the launchers and the
# packaging step call -- so it is put on the path rather than imported from.
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "build"))
check_deps = importlib.import_module("check_deps")


# --- reading pyproject ----------------------------------------------------------------
def test_the_distribution_name_comes_out_of_the_requirement():
    assert check_deps.name_of("python-can[serial]>=4.4") == "python-can"
    assert check_deps.name_of("PySide6-Essentials>=6.7") == "PySide6-Essentials"
    assert check_deps.name_of("bincopy>=20.0") == "bincopy"
    assert check_deps.name_of("pywin32>=306; sys_platform == 'win32'") == "pywin32"


def test_a_windows_only_requirement_is_not_wanted_on_linux():
    """Otherwise every start on Linux would offer to install pywin32."""
    requirement = "pywin32>=306; sys_platform == 'win32'"
    assert check_deps.wanted(requirement, platform="win32")
    assert not check_deps.wanted(requirement, platform="linux")
    assert check_deps.wanted("cantools>=39", platform="linux"), "no marker means everywhere"


def test_a_marker_that_is_not_understood_is_left_alone():
    """Guessing that it applies would mean reinstalling on every single start."""
    assert not check_deps.wanted("something>=1; python_version < '3.13'")


def test_this_environment_has_what_the_project_asks_for():
    assert check_deps.missing() == []


def test_a_dependency_that_is_not_installed_is_named(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["bincopy>=20", "nosuchpackage-xyz>=1"]\n', encoding="utf-8"
    )
    assert check_deps.missing(pyproject) == ["nosuchpackage-xyz"]


# --- a dependency replaced by another under the same import name ------------------------
def _installed(*names):
    return lambda name: name in names


@pytest.fixture
def replaced(monkeypatch):
    """pyflashgui has replaced nothing yet, so the check is given a pair."""
    monkeypatch.setattr(check_deps, "REPLACED", {"can-j1939": "python-can-j1939"})


def test_a_replaced_package_is_taken_out_before_the_install(replaced):
    """Two distributions that install into the same folder. pip cannot be
    told one replaces the other, so the launcher has to take the old one out."""
    assert check_deps.replaced_here(_installed("can-j1939")) == ["can-j1939"]


def test_both_go_when_both_are_there(replaced):
    """Removing the old one deletes files the two share, and pip would still
    think the new one was whole -- so it goes too, and the install puts it back."""
    stale = check_deps.replaced_here(_installed("can-j1939", "python-can-j1939"))
    assert stale == ["can-j1939", "python-can-j1939"]


def test_the_replacement_alone_is_left_alone(replaced):
    assert check_deps.replaced_here(_installed("python-can-j1939")) == []


def test_a_uv_environment_is_uninstalled_through_uv(monkeypatch):
    """`uv venv` makes an environment without pip in it."""
    monkeypatch.setattr(check_deps.importlib.util, "find_spec", lambda _name: None)
    assert check_deps.uninstall_command(["can-j1939"], "py")[:3] == ["uv", "pip", "uninstall"]


def test_a_pip_environment_is_uninstalled_through_pip():
    command = check_deps.uninstall_command(["can-j1939"], "py")
    assert command == ["py", "-m", "pip", "uninstall", "-y", "can-j1939"]


def test_the_check_uninstalls_then_reports_what_is_missing(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(check_deps, "replaced_here", lambda: ["can-j1939"])
    monkeypatch.setattr(check_deps.subprocess, "run", lambda command, **_k: ran.append(command))
    monkeypatch.setattr(check_deps, "missing", lambda: ["python-can-j1939"])
    assert check_deps.main() == 1
    assert ran and "can-j1939" in ran[0]
    assert capsys.readouterr().out.split() == ["python-can-j1939"], "and nothing else is printed"


# --- the entry point ------------------------------------------------------------------
def test_a_missing_library_is_a_dialog_rather_than_a_silent_death(app, monkeypatch):
    """pythonw has nowhere to print, so the last chance to say anything is a window."""
    import pyflashgui.__main__ as entry

    shown = []
    monkeypatch.setattr(messages, "critical", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.Ok)  # the notice
    # None in sys.modules is what Python turns into an ImportError on import.
    monkeypatch.setitem(sys.modules, "pyflashgui.ui.main_window", None)
    monkeypatch.setattr(sys, "argv", ["pyflashgui"])

    assert entry.main() == 1
    assert shown
    assert "pyflashgui.cmd" in shown[0], "and say what to do about it"


class _Window:
    """What note_a_slow_start needs of a window: somewhere to say things,
    and a folder to leave the report in."""

    def __init__(self, folder):
        self.said = []
        self.events = type("Events", (), {"information": lambda _s, text: self.said.append(text)})()
        self.ctx = type("Ctx", (), {"user_dir": folder})()


@pytest.mark.parametrize(
    ("took", "asked", "said", "reported"),
    [(29.0, False, True, False), (2.5, False, False, False), (2.5, True, False, True)],
)
def test_a_slow_start_says_where_to_look_and_timing_prints_it_all(
    tmp_path, monkeypatch, took, asked, said, reported
):
    """A slow start says so in one line and points to Help > Diagnostics,
    which always has the report; the whole report in the Event Log is for
    --timing, which asked for it."""
    import pyflashgui.__main__ as entry
    from pyflashgui.core import slow_start, timing

    monkeypatch.setattr(timing, "enabled", lambda: asked)
    monkeypatch.setattr(timing, "total_work", lambda: took)
    monkeypatch.setattr(timing, "report_lines", lambda: ["the report"])
    monkeypatch.setattr(slow_start, "compiled_this_start", lambda *_a: 0)
    window = _Window(tmp_path)

    entry.note_a_slow_start(window)

    assert any("Diagnostics" in line for line in window.said) is said
    assert ("the report" in window.said) is reported
    assert (tmp_path / timing.REPORT_NAME).exists() is reported


@pytest.mark.parametrize(
    ("argv", "env", "names"),
    [
        (["pyflashgui", "--timing"], "", "--timing"),
        (["pyflashgui"], "1", "PYFLASHGUI_TIMING"),
    ],
)
def test_the_report_says_why_it_is_there(monkeypatch, argv, env, names):
    """A --timing left in a shortcut after one investigation turns the report
    up at every start, so it says where it came from and how to stop it."""
    from pyflashgui.core import timing

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setenv("PYFLASHGUI_TIMING", env)
    fresh = importlib.reload(timing)
    assert names in fresh.why_shown()


def test_the_reason_comes_first_in_the_event_log(tmp_path, monkeypatch):
    import pyflashgui.__main__ as entry
    from pyflashgui.core import timing

    monkeypatch.setattr(timing, "why_shown", lambda: "the reason")
    monkeypatch.setattr(timing, "report_lines", lambda: ["the report"])
    window = _Window(tmp_path)
    entry.report(window)
    assert window.said[:2] == ["the reason", "the report"]


def test_the_selftest_covers_the_libraries_that_move_firmware():
    import pyflashgui.__main__ as entry

    assert "bincopy" in entry.SELFTEST_MODULES
    assert entry.selftest() == 0


# --- the launchers themselves ---------------------------------------------------------
@pytest.mark.parametrize("name", ("pyflashgui.cmd", "pyflashgui.sh"))
def test_the_launcher_checks_before_every_start(name):
    """Not only when .venv is absent -- that was the whole bug."""
    text = (PROJECT / name).read_text(encoding="utf-8")
    assert "check_deps.py" in text, f"{name} never notices a new dependency"
    assert 'install -e "."' in text
    assert ".[dev]" not in text, "a user's launcher has no business installing the test tools"


def test_the_shell_launcher_is_executable_in_git():
    """Reported: ./pyflashgui.sh on a fresh Linux clone said permission denied.
    Windows keeps no executable bit, so it has to be recorded in git itself."""
    import shutil
    import subprocess

    if shutil.which("git") is None or not (PROJECT / ".git").exists():
        pytest.skip("not a git checkout")
    staged = subprocess.run(
        ["git", "ls-files", "-s", "pyflashgui.sh"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if not staged:
        pytest.skip("pyflashgui.sh is not in git yet")
    assert staged.startswith("100755"), staged


# --- a .venv whose Python has gone ----------------------------------------------------
# A .venv is made from one Python. Uninstall that one, or replace it with a
# newer version, and the .venv cannot start: under pythonw that was a window
# that never opened, and the launcher took a dangling link for a first run.


@pytest.mark.parametrize("name", ("pyflashgui.cmd", "pyflashgui.sh"))
def test_the_launcher_offers_to_make_a_venv_again_when_its_python_has_gone(name):
    text = (PROJECT / name).read_text(encoding="utf-8")
    assert "not there any more" in text
    assert "Delete .venv and set it up again" in text


@pytest.mark.parametrize("name", ("pyflashgui.cmd", "pyflashgui.sh"))
def test_uv_makes_the_venv_from_the_python_that_was_checked(name):
    text = (PROJECT / name).read_text(encoding="utf-8")
    assert "uv venv --python" in text


def test_the_windows_launcher_prefers_a_python_every_library_has_a_download_for():
    """hidapi, which pyOCD needs on Windows, had no 3.15 download, so a .venv
    made from 3.15 failed to build it on any computer without a C compiler."""
    text = (PROJECT / "pyflashgui.cmd").read_text(encoding="utf-8")
    assert "for %%V in (3.14 3.13 3.12)" in text
    assert "py -%%V" in text and '"%PYEXE%" -m venv .venv' in text
    assert "python -m venv" not in text, "never the python on the PATH by name"


def test_a_failed_setup_does_not_keep_a_venv_made_with_the_wrong_python():
    """Reported: after a failed setup on 3.15, installing 3.14 changed nothing,
    because the .venv made with 3.15 was still there and used again."""
    text = (PROJECT / "pyflashgui.cmd").read_text(encoding="utf-8")
    failed = text[text.index("\n:fail\nset") :]
    assert "if defined FIRSTRUN goto :failfirst" in failed, "a first setup's goes unasked"
    label = failed.index("\n:failfirst\n")
    first = failed[label:]
    assert 'rmdir /s /q ".venv"' in first
    asked = failed[:label]
    assert "choice /c YN" in asked and 'rmdir /s /q ".venv"' in asked, "a later one's is asked"


def _broken_venv(folder: Path, home: str) -> None:
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (folder / ".venv" / "pyvenv.cfg").write_text(
        f"home = {home}\ninclude-system-site-packages = false\nversion = 3.14.6\n",
        encoding="utf-8",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
@pytest.mark.parametrize("answer", ("N", "Y"))
def test_the_windows_launcher_asks_before_deleting_a_venv_whose_python_has_gone(tmp_path, answer):
    import shutil
    import subprocess

    shutil.copy(PROJECT / "pyflashgui.cmd", tmp_path)
    _broken_venv(tmp_path, r"C:\Program Files\No Such Python 3.14")
    # No Python on the PATH: after Yes, setting up again stops at the first step.
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    said = subprocess.run(
        ["cmd", "/c", str(tmp_path / "pyflashgui.cmd")],
        cwd=tmp_path,
        input=f"{answer}\r\n\r\n",
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(system)},
        timeout=60,
    ).stdout
    assert r"C:\Program Files\No Such Python 3.14" in said, "the whole path, spaces and all"
    if answer == "N":
        assert "left as it is" in said and (tmp_path / ".venv").exists()
    else:
        assert not (tmp_path / ".venv").exists()
        assert "First run: setting up pyflashgui" in said


def _shell_check(folder: Path) -> Path:
    """The shell launcher, as far as its .venv check, and a word if it got past it."""
    text = (PROJECT / "pyflashgui.sh").read_text(encoding="utf-8")
    cut = text.index("if [ ! -x .venv/bin/python ]; then\n")
    script = folder / "pyflashgui.sh"
    script.write_text(text[:cut] + 'echo "GOT PAST THE CHECK"\n', encoding="utf-8")
    return script


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links and sh")
def test_the_shell_launcher_takes_a_link_to_a_python_that_has_gone_for_what_it_is(tmp_path):
    import subprocess

    script = _shell_check(tmp_path)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").symlink_to(tmp_path / "no-such-python3.14")
    said = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert said.returncode == 1, "no terminal to ask in, so it says what to do and stops"
    assert "not there any more" in said.stdout and "GOT PAST" not in said.stdout
    assert (tmp_path / ".venv").exists(), "and deletes nothing it was not told to"


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links and sh")
@pytest.mark.parametrize("made", ("3.1", "this one"))
def test_the_shell_launcher_notices_a_python_replaced_by_another_version(tmp_path, made):
    import subprocess

    script = _shell_check(tmp_path)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    python = Path(sys.executable).resolve()
    (tmp_path / ".venv" / "bin" / "python").symlink_to(python)
    version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.0" if made == "this one" else "3.1.0"
    )
    (tmp_path / ".venv" / "pyvenv.cfg").write_text(f"version = {version}\n", encoding="utf-8")
    said = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if made == "this one" or not python.name.startswith("python3."):
        assert "GOT PAST THE CHECK" in said.stdout, said.stdout + said.stderr
    else:
        assert "It was made with Python 3.1" in said.stdout


# --- the check that runs before every start ------------------------------------------------
@pytest.mark.parametrize("name", ("pyflashgui.cmd", "pyflashgui.sh"))
def test_the_dependency_check_is_not_repeated_for_an_unchanged_pyproject(name):
    """It costs a whole Python start -- a quarter of a second on every launch --
    to answer a question whose answer only changes when pyproject.toml does.

    So the answer is kept as a copy of the file it was the answer to: identical
    means asked and answered, and any edit at all asks again.
    """
    text = (PROJECT / name).read_text(encoding="utf-8")
    assert ".deps-ok" in text, f"{name} runs the check on every start"
    assert "check_deps.py" in text, "and still runs it when the answer could have changed"


@pytest.mark.parametrize("name", ("pyflashgui.cmd", "pyflashgui.sh"))
def test_the_stamp_is_only_written_after_a_good_answer(name):
    """A failed check remembered as an answer would be a .venv short of a
    library that nothing ever looks at again."""
    text = (PROJECT / name).read_text(encoding="utf-8")
    stamp = text.index(".deps-ok", text.index("check_deps.py"))
    installed = text.index('install -e "."')
    assert stamp > installed, f"{name} stamps before it has installed anything"


# --- startup timing ----------------------------------------------------------------
@pytest.fixture(autouse=True)
def _timing_left_as_found():
    """Reloading a module sticks, so put it back for whatever runs next."""
    yield
    import importlib

    from pyflashgui.core import timing

    importlib.reload(timing)


def test_the_report_is_off_unless_it_is_asked_for(monkeypatch):
    """The marks are always taken -- a start that turns out to have been slow
    cannot be measured afterwards -- but nothing is reported unasked."""
    import importlib

    from pyflashgui.core import timing

    monkeypatch.delenv(timing.ENV, raising=False)
    monkeypatch.setattr("sys.argv", ["pyflashgui"])
    fresh = importlib.reload(timing)
    assert not fresh.enabled(), "so __main__ writes no report"
    fresh.mark("something")
    assert fresh.total_work() > 0, "and the start is still measured"


def test_the_flag_turns_it_on_and_it_reports_each_step(monkeypatch, tmp_path):
    import importlib

    from pyflashgui.core import timing

    monkeypatch.setattr("sys.argv", ["pyflashgui", timing.FLAG])
    fresh = importlib.reload(timing)
    assert fresh.enabled()
    fresh.mark("first step")
    fresh.mark("second step")

    lines = fresh.report_lines()
    assert any("first step" in line for line in lines)
    assert any("second step" in line for line in lines)
    assert any("total" in line for line in lines)
    assert any("longest step" in line for line in lines), "it says which one to look at"

    written = fresh.write_report(tmp_path)
    assert written is not None and written.read_text(encoding="utf-8").count("step") >= 2


def test_the_environment_variable_turns_it_on_too(monkeypatch):
    import importlib

    from pyflashgui.core import timing

    monkeypatch.setattr("sys.argv", ["pyflashgui"])
    monkeypatch.setenv(timing.ENV, "1")
    assert importlib.reload(timing).enabled()
    monkeypatch.setenv(timing.ENV, "0")
    assert not importlib.reload(timing).enabled(), "0 means off, not 'set'"


def test_imports_are_attributed_to_the_package_they_are_in(monkeypatch):
    """The step that costs the most is usually 'libraries imported', which is
    no use on its own: the question is always which library."""
    import importlib
    import sys

    from pyflashgui.core import timing

    monkeypatch.setattr("sys.argv", ["pyflashgui", timing.FLAG])
    fresh = importlib.reload(timing)
    fresh.watch_imports()
    try:
        for name in ("wave", "colorsys", "difflib"):  # cheap, and rarely already in
            sys.modules.pop(name, None)
            importlib.import_module(name)
        lines = fresh.import_lines()
    finally:
        sys.meta_path[:] = [f for f in sys.meta_path if type(f).__name__ != "_TimedImports"]

    assert lines and "longest to import" in lines[0]
    assert any(fresh.STDLIB in line for line in lines)
    assert not any(line.endswith(("difflib", "wave", "colorsys")) for line in lines)


def test_the_standard_library_is_one_line_and_a_package_is_its_own():
    """json or ctypes on a line of its own reads as something installed."""
    from pyflashgui.core import timing

    assert timing._package("json.decoder") == timing.STDLIB
    assert timing._package("_ssl") == timing.STDLIB
    assert timing._package("canopen.sdo.client") == "canopen"


def test_the_report_says_the_notice_line_is_a_person_waiting(monkeypatch):
    """The libraries load behind the notice and the window is built after it,
    so the wait lands between two marks and looks like work."""
    import importlib

    from pyflashgui.core import timing

    monkeypatch.setattr("sys.argv", ["pyflashgui", timing.FLAG])
    fresh = importlib.reload(timing)
    fresh.mark("libraries imported")
    fresh.mark(fresh.NOTICE_STEP)
    fresh.mark("panes built")

    lines = fresh.report_lines()
    assert any(fresh.NOTICE_STEP in line for line in lines), "the wait is shown"
    assert any("not counting the wait" in line for line in lines), "and kept out of the total"


def test_the_launcher_stamp_is_read_in_both_shapes(monkeypatch):
    """A shell stamps epoch seconds, cmd stamps %TIME%, which is a clock
    reading; the report wants seconds either way."""
    import importlib
    import time as clock

    from pyflashgui.core import timing

    monkeypatch.delenv(timing.PYTHON_ENV, raising=False)
    monkeypatch.setenv(timing.LAUNCH_ENV, f"{clock.time() - 2.0:.3f}")
    timing = importlib.reload(timing)  # its clock is taken as it is imported
    took, _starting = timing.launcher_seconds()
    assert took is not None and 1.5 <= took <= 4.0

    now = clock.localtime()
    a_moment_ago = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec - 1
    hours, rest = divmod(max(a_moment_ago, 0), 3600)
    minutes, seconds = divmod(rest, 60)
    monkeypatch.setenv(timing.LAUNCH_ENV, f"{hours:02d}:{minutes:02d}:{seconds:02d}.00")
    took, _starting = timing.launcher_seconds()
    assert took is not None and 0 <= took <= 5


def test_a_stamp_from_an_older_run_is_ignored(monkeypatch):
    import importlib
    import time as clock

    from pyflashgui.core import timing

    timing = importlib.reload(timing)
    monkeypatch.delenv(timing.PYTHON_ENV, raising=False)
    monkeypatch.setenv(timing.LAUNCH_ENV, f"{clock.time() - 3600:.3f}")
    assert timing.launcher_seconds() == (None, None), "an hour is somebody else's launch"
    monkeypatch.setenv(timing.LAUNCH_ENV, "not a time")
    assert timing.launcher_seconds() == (None, None)
    monkeypatch.delenv(timing.LAUNCH_ENV)
    assert timing.launcher_seconds() == (None, None), "nothing stamped it, nothing to say"


def test_the_script_and_the_interpreter_are_counted_apart(monkeypatch):
    """Doing less in the script and starting Python faster are different
    problems, so one number for both would not say which to work on."""
    import importlib
    import time as clock

    from pyflashgui.core import timing

    now = clock.time()
    monkeypatch.setenv(timing.LAUNCH_ENV, f"{now - 3.0:.3f}")  # script began
    monkeypatch.setenv(timing.PYTHON_ENV, f"{now - 1.0:.3f}")  # python started
    script, interpreter = importlib.reload(timing).launcher_seconds()
    assert script is not None and 1.5 <= script <= 2.5, "the script's own two seconds"
    assert interpreter is not None and 0.5 <= interpreter <= 1.5


def test_the_launcher_is_not_charged_with_what_came_after_it(monkeypatch):
    """It measures to the moment timing was imported, not to the moment the
    report is written: the report comes after Qt, the libraries and the
    window, and charging those to the launcher made a fast start look slow."""
    import importlib
    import time as clock

    from pyflashgui.core import timing

    monkeypatch.setenv(timing.LAUNCH_ENV, f"{clock.time() - 0.5:.3f}")
    monkeypatch.delenv(timing.PYTHON_ENV, raising=False)
    fresh = importlib.reload(timing)
    first, _ = fresh.launcher_seconds()
    clock.sleep(0.3)  # as if the window were being built
    second, _ = fresh.launcher_seconds()

    assert first is not None and second is not None
    assert abs(second - first) < 0.05, "asking later must not make the answer bigger"


def test_the_total_leaves_out_the_time_spent_waiting_for_a_person(monkeypatch):
    """A total that grows because somebody read the notice slowly is a total
    nobody can compare against the last run."""
    import importlib
    import time as clock

    from pyflashgui.core import timing

    monkeypatch.setattr("sys.argv", ["pyflashgui", timing.FLAG])
    fresh = importlib.reload(timing)
    fresh.mark("libraries imported")
    clock.sleep(0.2)  # as if somebody were reading
    fresh.mark(fresh.NOTICE_STEP)
    fresh.mark("window on screen")

    total = next(line for line in fresh.report_lines() if "not counting the wait" in line)
    assert float(total.split()[0]) < 0.15, "the reading time is not part of it"


def test_the_diagnostics_report_says_how_long_starting_took(app, tmp_path, monkeypatch):
    """Always, without the flag: nobody thinks to ask for timing before the
    start they wanted to measure, and a report from a slow machine is where
    the question actually arrives."""
    from PySide6.QtCore import QSettings

    from pyflashgui.core import timing
    from pyflashgui.ui.help_menu import diagnostics
    from pyflashgui.ui.main_window import MainWindow

    monkeypatch.setenv("PYFLASHGUI_HOME", str(tmp_path))
    QSettings().clear()
    timing.mark("a step of some kind")
    timing.watch_imports()
    sys.modules.pop("colorsys", None)
    importlib.import_module("colorsys")
    window = MainWindow()

    report = diagnostics(window)

    assert "startup timing" in report.lower()
    assert "took longest to import" in report, "and which packages, every time"
    assert "total, not counting the wait" in report
    assert "Installed with them" in report, "what the packages brought, as well as the packages"
    window.close()


# --- Qt's X11 libraries -----------------------------------------------------------------
def test_a_missing_x11_library_is_named_with_its_package():
    from pyflashgui import __main__ as entry

    def load(library):
        if library == "libxcb-cursor.so.0":
            raise OSError(library)

    assert entry.missing_xcb_packages(load) == ["libxcb-cursor0"]
    assert entry.missing_xcb_packages(lambda library: None) == []


def test_the_x11_libraries_are_only_asked_for_where_qt_uses_x11(monkeypatch):
    from pyflashgui import __main__ as entry

    monkeypatch.setattr(sys, "platform", "linux")
    assert entry.uses_xcb({"XDG_SESSION_TYPE": "x11"})
    assert not entry.uses_xcb({"XDG_SESSION_TYPE": "wayland"})
    assert entry.uses_xcb({"XDG_SESSION_TYPE": "wayland", "QT_QPA_PLATFORM": "xcb"})
    assert not entry.uses_xcb({"QT_QPA_PLATFORM": "offscreen"})
    monkeypatch.setattr(sys, "platform", "win32")
    assert not entry.uses_xcb({})


def test_starting_without_them_stops_before_qt_with_the_install_line(monkeypatch, capsys):
    from pyflashgui import __main__ as entry

    monkeypatch.setattr(entry, "uses_xcb", lambda: True)
    monkeypatch.setattr(entry, "missing_xcb_packages", lambda: ["libxcb-cursor0"])
    monkeypatch.setattr(entry, "QApplication", None)  # reaching Qt would fail the test
    assert entry.main() == 1
    assert "sudo apt install libxcb-cursor0" in capsys.readouterr().err
