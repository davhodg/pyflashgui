@echo off
rem Launch pyflashgui. Sets itself up on first run (needs Python 3.12 or newer on
rem the PATH), then starts the application.
rem
rem The setup deliberately is not quiet: it downloads a couple of hundred
rem megabytes, mostly Qt, and a silent several-minute pause looks like a hang.
rem If "uv" is installed it is used instead of pip. The first run is limited by
rem the download whichever is used, but uv caches packages, so later rebuilds of
rem .venv take seconds.
rem
rem Batch files must keep CRLF line endings, or cmd.exe mis-parses labels and
rem goto; .gitattributes enforces that.
setlocal
cd /d "%~dp0"

rem Stamped before anything else so that --timing can say what this file
rem cost before Python was reached: the dependency check is a whole Python
rem start on its own, and none of it is visible from inside the application.
set PYFLASHGUI_LAUNCH_AT=%TIME%

if not exist ".venv\Scripts\python.exe" goto :setup

rem A .venv is made from one Python, and its python.exe only passes the
rem work on to that one, named as home in pyvenv.cfg. Uninstalled -- or
rem replaced by a newer version, which on Windows lives in a folder of its
rem own -- and python.exe cannot start, and pythonw says nothing about it:
rem the window simply never opens. Checked by looking for the file, which
rem costs nothing, rather than by starting Python.
set "VENV_HOME="
if exist ".venv\pyvenv.cfg" for /f "usebackq tokens=1,* delims== " %%A in (".venv\pyvenv.cfg") do if /i "%%A"=="home" set "VENV_HOME=%%B"
if defined VENV_HOME if not exist "%VENV_HOME%\python.exe" goto :gone
goto :check

:setup
echo.
echo ============================================================
echo  First run: setting up pyflashgui
echo ============================================================
echo.
echo  pyflashgui is written in Python, and needs a set of libraries
echo  to run. Rather than install those into the Python on your
echo  machine -- where they could clash with something else --
echo  they go into a "virtual environment": a self contained
echo  folder called .venv, right next to this script, holding its
echo  own copy of Python and only the libraries pyflashgui needs.
echo.
echo  Nothing outside that folder is touched, and deleting .venv
echo  undoes the whole thing.
echo.
echo  This runs once. It downloads a couple of hundred megabytes, most of it Qt
echo  (the toolkit the windows are drawn with), so expect a few
echo  minutes. Every later start is immediate.
echo.

echo  [1/3] Checking Python...
rem Which Python .venv is made from, by its full path: the same one checks,
rem builds .venv and, through uv, is used by uv, which left to itself chooses
rem by rules of its own and can even fetch a Python of its own.
rem
rem The newest of these that is installed comes first, asked of the py
rem launcher by version: every library pyflashgui runs on has a ready-made
rem download for them on Windows. A Python newer than that has pip build the
rem missing ones from source -- hidapi, which pyOCD needs, is one -- and that
rem needs a C compiler most computers do not have. Add a version here once
rem every library has a download for it.
rem
rem Without py, or with none of these, it is whatever python is on the PATH.
set "PYEXE="
set "PY="
where py >nul 2>&1 && set PY=1
if defined PY for %%V in (3.14 3.13 3.12) do if not defined PYEXE for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE (
    python --version >nul 2>&1
    if errorlevel 1 goto :nopython
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "PYEXE=%%P"
)
"%PYEXE%" --version
"%PYEXE%" -c "import sys; sys.exit(sys.version_info < (3, 12))"
if errorlevel 1 goto :oldpython
rem From here on, a failure leaves no half-made .venv behind: the next run
rem would take it for a finished one and never choose a Python again.
set FIRSTRUN=1

rem uv is a much faster drop-in replacement for pip. Used if it happens to be
rem installed; never required.
set UV=
where uv >nul 2>&1 && set UV=1
if defined UV echo        uv found: using it instead of pip.

echo.
echo  [2/3] Creating the virtual environment in .venv ...
if defined UV (
    uv venv --python "%PYEXE%" .venv
) else (
    "%PYEXE%" -m venv .venv
    if errorlevel 1 goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)
if errorlevel 1 goto :fail

echo.
echo  [3/3] Installing pyflashgui and the libraries it runs on.
echo        Not the test tools -- see CONTRIBUTING.md if you want those.
echo        Each package is listed as it downloads; the big one is
echo        PySide6, which is Qt.
echo.
if defined UV (
    uv pip install --python ".venv\Scripts\python.exe" -e "."
) else (
    ".venv\Scripts\python.exe" -m pip install -e "."
)
if errorlevel 1 goto :fail

rem Nothing is asked here, and no shortcut is made: a question at the end of
rem several minutes of downloading is one nobody is there to answer. pyflashgui
rem says once, in its Event Log, where a shortcut is made.
echo.
echo ============================================================
echo  Setup finished. Starting pyflashgui...
echo ============================================================
echo.
echo  For a shortcut in the Start menu or on the desktop, see
echo  Settings in the Tools menu.
if not defined UV (
    echo.
    echo  Tip: "pip install uv" once, and this setup takes seconds
    echo  rather than minutes the next time you do it.
)
echo.


rem A .venv built before a dependency was added is short of it, and the
rem launcher below runs pythonw, which has no console for the ImportError
rem to appear in: the window would simply never open. So ask -- but only
rem when the answer could have changed.
rem
rem The check costs a whole Python start, a quarter of a second on every
rem launch, to answer a question whose answer only changes when pyproject.toml
rem does. So the answer is kept as a copy of the file it was the answer to,
rem and fc compares the two: identical means asked and answered already.
:check
fc /b "pyproject.toml" ".venv\.deps-ok" >nul 2>&1
if not errorlevel 1 goto :run
".venv\Scripts\python.exe" "build\check_deps.py" >nul 2>&1
if not errorlevel 1 goto :stamp
echo.
echo  pyflashgui needs libraries that this folder does not have yet.
echo  Installing them; this is much quicker than the first setup was.
echo.
set UV=
where uv >nul 2>&1 && set UV=1
if defined UV (
    uv pip install --python ".venv\Scripts\python.exe" -e "."
) else (
    ".venv\Scripts\python.exe" -m pip install -e "."
)
if errorlevel 1 goto :fail

rem Written only after a successful check or install, so a failed one is asked
rem again next time rather than remembered as an answer.
:stamp
copy /y "pyproject.toml" ".venv\.deps-ok" >nul

:run
rem Stamped again here, so --timing can tell this file's own work apart
rem from starting the interpreter: the two have different cures.
set PYFLASHGUI_PYTHON_AT=%TIME%
start "" ".venv\Scripts\pythonw.exe" -m pyflashgui %*
exit /b 0

:gone
echo.
echo  pyflashgui's .venv folder was made with a Python that is not there any more:
echo.
echo      %VENV_HOME%
echo.
echo  It was probably uninstalled, or replaced by a newer version.
echo.
echo  .venv holds only the libraries pyflashgui runs on, made for that Python,
echo  so it has to be made again with the Python installed now. Your
echo  workspaces and settings are not in it, and are kept.
echo.
choice /c YN /m " Delete .venv and set it up again"
if errorlevel 2 goto :keepvenv
rmdir /s /q ".venv"
if exist ".venv" goto :cannotdelete
goto :setup

:keepvenv
echo.
echo .venv was left as it is, and pyflashgui cannot start until it is made
echo again: delete the .venv folder beside this script, and run it again.
pause
exit /b 1

:cannotdelete
echo.
echo .venv could not be deleted completely: something may still be using it.
echo Close pyflashgui if it is open, delete the .venv folder beside this
echo script by hand, and run it again.
pause
exit /b 1

:nopython
echo.
echo Python was not found.
echo Install Python 3.14: with the Python Install Manager, "py install 3.14";
echo or from https://www.python.org/downloads/, ticking "Add python.exe to PATH".
pause
exit /b 1

:oldpython
echo.
echo pyflashgui needs Python 3.12 or newer, and the python on the PATH is older.
echo Install Python 3.14: with the Python Install Manager, "py install 3.14";
echo or from https://www.python.org/downloads/, ticking "Add python.exe to PATH".
pause
exit /b 1

:fail
set "FAILED=%errorlevel%"
echo.
echo Setup failed ^(errorlevel %FAILED%^). The messages above say why. The
echo usual causes are:
echo.
echo  - no internet connection, or a proxy that blocks pypi.org;
echo  - "Failed to build" in the messages: a Python newer than every library
echo    pyflashgui runs on has a ready-made download for, so one had to be
echo    built from source. Python 3.14 has them all: "py install 3.14", and
echo    run this again -- it is chosen over a newer one by itself.
if defined FIRSTRUN (
    rmdir /s /q ".venv" >nul 2>&1
    echo.
    echo The half-made .venv was removed, so the next run starts again.
)
pause
exit /b 1
