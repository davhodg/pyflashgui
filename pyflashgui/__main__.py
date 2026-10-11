# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Entry point: `python -m pyflashgui`, or the `pyflashgui` command pip installs."""

# Deliberately out of order (hence the noqa): timing's clock starts when it is
# imported, so it has to come before the imports whose cost is being measured.
# It pulls in nothing but the standard library.
import importlib  # noqa: I001
import os
import sys

from pyflashgui.core import timing
from PySide6.QtWidgets import QApplication

from pyflashgui import APP_NAME

#: Imported by ``--selftest``. These are the modules a packaged build is most
#: likely to be missing, because they are loaded by name at run time and so no
#: static analysis can see them.
SELFTEST_MODULES = (
    "bincopy",
    "pyocd",
    "pyocd.core.helpers",
    "pyocd.flash.file_programmer",
    "pyocd.flash.eraser",
    "cmsis_pack_manager",
    "usb.core",
    "libusb_package",
    "pyflashgui.core.images",
    "pyflashgui.core.memory_map",
    "pyflashgui.backends.pyocd_backend",
    "pyflashgui.backends.jlink_backend",
    "pyflashgui.backends.simulated",
    "pyflashgui.ui.main_window",
)

#: The probe drivers pyOCD has to be able to find. It looks them up through
#: entry points, which a build that left pyOCD's package metadata behind
#: does not have: every one of them would then be missing, with no error.
#: Not the J-Link driver, which pyOCD only offers where SEGGER's own library
#: is installed, and that is the user's to install.
PROBE_DRIVERS = ("cmsisdap", "picoprobe", "stlink")

#: Targets that are part of pyOCD itself rather than a CMSIS-Pack, and so
#: have to work in a build with no packs installed.
BUILTIN_TARGETS = ("cortex_m", "rp2040", "rp2350")


def missing_probe_drivers() -> list[str]:
    """The PROBE_DRIVERS pyOCD cannot load here."""
    from pyocd.probe.aggregator import PROBE_CLASSES

    return [name for name in PROBE_DRIVERS if name not in PROBE_CLASSES]


def missing_builtin_targets() -> list[str]:
    """The BUILTIN_TARGETS this pyOCD does not have."""
    from pyocd.target import builtin

    return [name for name in BUILTIN_TARGETS if name not in builtin.BUILTIN_TARGETS]


def selftest() -> int:
    """Import everything a build could plausibly be missing. Exit code only:
    a windowed build has nowhere to print to."""
    failures = []
    for name in SELFTEST_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"{name}: {exc}")

    try:
        failures += [f"pyOCD probe driver {name}: not found" for name in missing_probe_drivers()]
        failures += [f"pyOCD target {name}: not found" for name in missing_builtin_targets()]
    except Exception as exc:
        failures.append(f"pyocd: {exc}")

    # libusb is a native library carried inside a Python package, which is
    # the kind of file a build leaves behind. Without it pyOCD lists no
    # CMSIS-DAP v2 probe and no ST-Link, and says nothing about why.
    try:
        import libusb_package

        if libusb_package.get_libusb1_backend() is None:
            failures.append("libusb: the library libusb-package carries would not load")
    except Exception as exc:
        failures.append(f"libusb: {exc}")

    # The manual is package data, so it is exactly the kind of file a build
    # drops silently. Every page, by name: one missing page is a topic that
    # vanished, and a manual that still opens is the worst way for that to
    # be found.
    try:
        from pyflashgui.help import missing_images, missing_pages

        for page in missing_pages():
            failures.append(f"pyflashgui/help/{page}: not shipped with this build")
        for image in missing_images():
            failures.append(f"pyflashgui/help/{image}: shown in the manual but not shipped")
    except Exception as exc:
        failures.append(f"pyflashgui.help: {exc}")

    # Help > Licences reads these at run time from beside the executable. A
    # build that ships them where _find cannot see them would show three empty
    # tabs, and no import check would notice.
    try:
        from pyflashgui.ui.help_menu import missing_licence_files

        failures += [
            f"{name}: not found beside the application"
            for name in missing_licence_files(getattr(sys, "frozen", False))
        ]
    except Exception as exc:
        failures.append(f"pyflashgui.ui.help_menu: {exc}")

    if failures:
        sys.stderr.write("selftest failures:" + "".join(f"\n  {f}" for f in failures) + "\n")
        return 1
    return 0


#: Who Windows thinks the windows belong to. Without one, a pyflashgui started
#: from source is grouped under pythonw.exe and the taskbar shows Python's
#: icon whatever the window says -- the window icon only reaches the title bar.
APP_USER_MODEL_ID = "davhodg.pyflashgui"


def set_icon(app) -> None:
    """The application icon, before any window exists.

    Set on the application rather than on the main window so that a message
    shown during start-up carries it too. The .ico rather than the PNG:
    it holds each size drawn for that size, and Qt picks the nearest one.
    """
    from PySide6.QtGui import QIcon

    from pyflashgui import resources

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):  # an unusual shell: the title bar still has it
            pass
    app.setWindowIcon(QIcon(str(resources.path("pyflashgui.ico"))))


#: The libraries Qt's X11 plugin needs that Debian, Ubuntu and Linux Mint can
#: leave out, each with the package it comes in. Without one, Qt stops with
#: "could not load the Qt platform plugin xcb" and does not say which.
XCB_LIBRARIES = (
    ("libxcb-cursor.so.0", "libxcb-cursor0"),
    ("libxcb-icccm.so.4", "libxcb-icccm4"),
    ("libxcb-image.so.0", "libxcb-image0"),
    ("libxcb-keysyms.so.1", "libxcb-keysyms1"),
    ("libxcb-render-util.so.0", "libxcb-render-util0"),
    ("libxkbcommon-x11.so.0", "libxkbcommon-x11-0"),
)


def uses_xcb(environ=None) -> bool:
    """Whether Qt will draw through X11 here, where XCB_LIBRARIES are needed."""
    if not sys.platform.startswith("linux"):
        return False
    environ = os.environ if environ is None else environ
    chosen = environ.get("QT_QPA_PLATFORM", "")
    if chosen:
        return chosen.startswith("xcb")
    return environ.get("XDG_SESSION_TYPE") != "wayland"


def missing_xcb_packages(load=None) -> list[str]:
    """The packages to install for the XCB_LIBRARIES that cannot be loaded."""
    if load is None:
        import ctypes

        load = ctypes.CDLL
    missing = []
    for library, package in XCB_LIBRARIES:
        try:
            load(library)
        except OSError:
            missing.append(package)
    return missing


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if uses_xcb() and (missing := missing_xcb_packages()):
        sys.stderr.write(
            "Qt needs libraries this system does not have to draw the window. On Debian,\n"
            "Ubuntu and Linux Mint:\n\n"
            f"    sudo apt install {' '.join(missing)}\n"
        )
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)  # QSettings uses these two for the registry/ini path
    set_icon(app)
    # Before anything is drawn, so the first window is already in the colours chosen.
    from pyflashgui.ui import theme

    theme.apply(theme.chosen())
    timing.mark("Qt started")
    # From here on, which package each imported second belongs to. Installed
    # after Qt because Qt is already in by now, and its cost is its own line.
    timing.watch_imports()

    # Imported here rather than at the top of the file so that a library
    # which is not installed becomes a dialog. Started from pyflashgui.cmd
    # there is no console -- it runs pythonw -- so an ImportError on the way
    # up is a window that never appears and not one word about why.
    try:
        from pyflashgui.ui.main_window import MainWindow
        from pyflashgui.ui.session import Session

        timing.mark(timing.LIBRARIES_STEP)
    except Exception as failed:
        # Not ImportError alone. A library that is installed and will not
        # load fails however it likes, and anything not caught here is a
        # window that never appears.
        from pyflashgui.ui import messages

        messages.critical(None, f"{APP_NAME} cannot start", why_it_cannot_start(failed))
        sys.stderr and sys.stderr.write(why_it_cannot_start(failed) + "\n")
        return 1

    # Held by a Session rather than a local, because switching workspace
    # replaces the window rather than reconfiguring it.
    session = Session(MainWindow)
    window = session.open()
    timing.mark("window on screen")
    note_a_slow_start(window)
    return app.exec()


def why_it_cannot_start(failed: BaseException) -> str:
    """What to tell somebody whose libraries would not load, and what to do.

    Two different faults. A library that is not there is put right by
    installing it. One that is there and will not load is usually two
    libraries that no longer agree -- a new release of one, which the other
    was not written for -- and installing again changes nothing: it wants the
    name of the file that failed, so that the pair can be found.
    """
    if isinstance(failed, ModuleNotFoundError):
        return (
            f"A library {APP_NAME} needs is missing:\n\n    {failed}\n\n"
            "Start it with pyflashgui.cmd (or pyflashgui.sh), which installs "
            "anything missing before starting, or install it with pip."
        )
    import traceback

    where = traceback.extract_tb(failed.__traceback__)
    place = f"\n    in {where[-1].filename}, line {where[-1].lineno}" if where else ""
    return (
        f"A library {APP_NAME} needs is installed but would not load:\n\n"
        f"    {type(failed).__name__}: {failed}{place}\n\n"
        "This is usually two libraries that no longer agree, after a new release "
        "of one of them. Upgrading the one named above, or going back a version "
        "of the one it was loading, normally puts it right; in a source folder, "
        "deleting .venv and starting the launcher installs them all again."
    )


def note_a_slow_start(window) -> None:
    """What starting had to do and how long it took, as far as it is worth saying.

    Two separate lines, each only when there is something to say: how many
    files Python compiled, and -- for a slow start -- what took over a second,
    with a pointer to *Help > Diagnostics*, which always has the whole report.
    ``--timing`` puts the whole report in the Event Log after every start.
    """
    from pyflashgui.core import slow_start

    if (compiled := slow_start.compiled_note(timing.started_at())) is not None:
        window.events.information(compiled)
    slow = slow_start.message(
        timing.total_work(), steps=timing.step_times(), packages=timing.import_times()
    )
    if slow is not None:
        window.events.information(slow)
    if timing.enabled():
        report(window)


def report(window) -> None:
    """Say where the time went, in the Event Log and in a file.

    Both, because the launcher starts pythonw and there is no console to
    print to, and because a number somebody has to read off the screen is a
    number that does not reach a bug report.
    """
    for line in [timing.why_shown(), *timing.report_lines()]:
        window.events.information(line)
    if (path := timing.write_report(window.ctx.user_dir)) is not None:
        window.events.information(f"Startup timing written to {path}")


if __name__ == "__main__":
    sys.exit(main())
