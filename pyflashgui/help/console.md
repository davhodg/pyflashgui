[&larr; Contents](manual.md)

# Python Console

*View > Python Console* opens a Python prompt inside pyflashgui, with the probe and the target to hand as `flash`. It is for what the buttons do not do by themselves: reading the same word over and over to watch it change, putting a test pattern into RAM, programming two images in turn, or a loop that programs, resets and reads back.

It behaves like the `python` prompt: a block over several lines carries on with `...`, Up and Down go back through what was typed, and a mistake shows Python's own traceback. The box typed into takes several lines too: **Shift+Enter** starts another, indented as the one before and further after a colon, and several lines pasted at once arrive as they are. **Enter** then runs them all together, each value shown as the prompt shows it, and **Tab** indents. **Run script...** runs a `.py` file with the same names. **Stop** stops a line or a script, and **Clear** clears the pane.

**File > Run script...** does the same from the menu, and shows the console first, so that what the script prints can be read. **File > Recent scripts** lists the last five run in the workspace, by either, newest first: one click runs one again. A script kept in the workspace's folder is remembered by where it is in it, and found wherever the workspace is taken.

## The names

| Name | What it is |
|---|---|
| `flash` | the probe and the target: see below |
| `files` | the Files pane, with `files.entries` and `files.add_files([...])` |
| `log(text)` | a line in the [Event Log](manual.md) |
| `wait(seconds)` | let the window run for that long: a script's `sleep` |
| `window`, `ctx` | the main window, and the settings and folders of the workspace |
| `ScriptError` | what `flash` raises when it could not do what it was asked |

## flash

Each call does what the button of the same name does -- the same checks, the same questions and the same lines in the Event Log -- and then waits for it to finish, so a script reads in the order it runs:

```python
flash.connect()
flash.program("C:/work/app.hex")
print(flash.read(0x20000000, 16).hex(" "))
```

| Call | What it does |
|---|---|
| `connect(probe=None, target=None)` | connect, to what the bar has chosen unless told otherwise; nothing if that is connected already |
| `disconnect()` | let go of the probe |
| `read(address, length, show=False)` | that many bytes of the target's memory, as `bytes`. `show=True` also lists them in Files as a read |
| `write(address, data)` | write bytes to RAM or a peripheral's registers. Never to flash, which is programmed |
| `erase()`, `erase(address, length)` | erase all of the flash, or every sector a range falls in |
| `program(*files, address=None, verify=True, erase=True, reset=False)` | program these files, or what is ticked in Files when none are named; `address` is where a raw binary goes; `erase=False` writes to flash erased beforehand, erasing nothing. Checked against the memory map first. The target is left stopped unless `reset` |
| `verify(*files, address=None)` | whether the target holds these files, or what is ticked: `True` or `False` |
| `reset(halt=False, kind="default")` | restart the target, stopped at its first instruction if `halt`; through pyOCD `kind` can be `"pin"`, `"system"` or `"core"`, as under the arrow beside **Reset** |
| `show(address, data)` | list bytes in Files as a read, to look at, compare or save |
| `connected`, `target`, `probe`, `regions` | what is connected, and the target's memory |

A call that does not do what it was asked -- nothing connected, a file that does not fit, a read the probe refused, a question answered No -- raises `ScriptError` with the sentence the Event Log has, so that a script does not carry on as if it had. A target that differs from a file is an answer rather than a failure: `verify` returns `False`.

**Program and Erase ask first**, as their buttons do, unless that question was ticked away earlier. A script is asked what anybody pressing the button would be asked.

A read made by a script is not added to Files unless `show=True` says so: a loop reading the same word a hundred times wants the bytes, not a hundred reads in the list.

## Waiting, and stopping

The console runs on the window's own thread. That is what lets it touch the window and the panes, and it is why `wait(seconds)` is there: `time.sleep` stops the window, and **Stop** with it.

While a `flash` call or a `wait` is waiting, the window carries on: the progress bar moves, and **Cancel** in the Files pane cancels a read or a verify, which the script sees as a `ScriptError`. **Stop** stops the script at the next `flash` call or `wait`, cancelling what the probe is doing if it can be cancelled. Programming cannot: it finishes first. A loop that never calls either cannot be stopped from the window, so give a long one a `wait(0)` now and then.

pyflashgui does not close while a script is running: stop it first.

## An example

Program a file, then watch a counter in RAM for ten seconds:

```python
flash.connect()
flash.program("C:/work/app.hex")
for second in range(10):
    count = int.from_bytes(flash.read(0x20000100, 4), "little")
    print(second, count)
    wait(1)
```
