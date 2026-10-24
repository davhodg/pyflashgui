[&larr; Contents](manual.md)

# About, licences and updates

**Help > Documentation** opens this manual. It ships inside pyflashgui; *Back* and *Contents* get you around it.

**Help > Diagnostics...** opens a report in a window of its own, and copies it to the
clipboard as it opens -- ready to paste into a bug report. **Refresh** makes it again,
**Copy** copies it again and **Save...** writes it to a file. It gives:

- the versions of pyflashgui, Python and every package it runs on;
- **the connection**: what is chosen under Using, Probe, Target and Speed, what is
  connected, and whether anything is being done; through pyOCD, the options pyOCD was
  given, whether the target is built in, from a pack or the generic Cortex-M, its cores and
  the probe's wire protocol; through J-Link Commander, how Commander is run;
- the probes found when they were last looked for;
- the target's memory as pyflashgui has it, and what the memory map says of the files
  ticked;
- each entry in the Files pane, and the Memory panes open;
- **the last twenty operations**, in order -- connecting, erasing, programming, reading,
  resetting -- each with how it ended and how long it took;
- **what pyOCD and pylink said for themselves**: their last hundred lines, from information
  up. Their errors are also put in the Event Log as they happen;
- the last twenty warnings and errors from the Event Log;
- J-Link Commander's location and every J-Link software folder found, and pyOCD's packs;
- the workspace, any confirmation not being asked, and the threads running;
- the panes out on their own, and how long starting took.

A part of it that cannot be read says so and the rest is still given. It names the probes'
serial numbers, the workspace folder and the files in the Files pane: remove any of that
from a bug report if you would rather.

The report names the version, and -- when pyflashgui is being run from a source checkout rather than an installed build -- the branch or tag and the commit it is on, read from `.git` without running git. Between two releases every build calls itself the same version, so that line is what tells one pull from another. It does not say whether any file has been edited since: that needs git itself, and the launcher runs without a console for it to use.

**Help > Check for updates...** asks the question that fits how pyflashgui was installed. The Windows installer's build asks GitHub whether there is a newer release, and offers to open the releases page. A pip installation asks PyPI for its newest version, and says the pip command that updates it. Run from a source folder, it asks about commits instead, since a release is behind everything pulled since: how many newer commits GitHub has on the branch this folder is on, and it offers to open the list of them. A branch GitHub does not have is compared with master.

**Help > Licences...** shows pyflashgui's own Apache-2.0 licence, the NOTICE attributions and the full third-party licence text, all shipped with the application.

**Help > About pyflashgui** shows the version alongside Python, every package pyflashgui runs on and the platform, in a form you can copy. It also says where it is running from: the Python it started with, that Python's environment, the folder the pyflashgui package was loaded from, and how it got there -- pip, an editable install of a source folder, or the Windows installer. On a computer with more than one Python that answers which one it is.

## If pyflashgui will not start

Started from the source folder, `pyflashgui.cmd` and `pyflashgui.sh` install anything missing before they start pyflashgui, and a library that is still missing is reported in a window rather than as nothing happening. The entry made by *Tools > Settings > Add shortcut to Start menu* (*Add shortcut to applications menu* on Linux), or by *Add shortcut to desktop* on Windows, starts the launcher too, so starting from it after a pull does the same. Installed with pip, the same two make a shortcut that starts pyflashgui with the Python it is installed in. The first start says where they are in the Event Log; the launchers ask nothing. On Linux, a library Qt needs to draw the window is named, with the package it comes in, before Qt is started: Qt itself says only that it could not load the "xcb" plugin. `python -m pyflashgui --selftest` imports everything a build is most likely to be missing, checks that pyOCD can find its probe drivers and targets, and exits with 0 if it is all there, which is how the build checks itself.

**If pyflashgui is slow to start**, the diagnostics report says where the seconds went: starting is measured on every run, step by step and package by package, so the breakdown is already there when somebody thinks to ask. A start that takes longer than usual says so in the Event Log and points to *Help > Diagnostics*. The first start after an update is the usual one: Python compiles every changed file again, and that start says how many it compiled. To have the whole report in the Event Log after every start, and in `startup-timing.txt` in pyflashgui's own folder, start pyflashgui with `--timing` -- `pyflashgui.cmd --timing`, or `pyflashgui.sh --timing` -- or set `PYFLASHGUI_TIMING=1`.
