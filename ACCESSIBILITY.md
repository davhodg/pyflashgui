# Accessibility

pyflashgui should be usable by anybody who programs microcontrollers, including people who use a
keyboard and no mouse, a screen reader, large text, or a high contrast theme. This page says what
that means here, what has been checked and what has not, and how to report something that gets
in your way.

It is a statement of what is aimed for and of what is known, not a claim of conformance to a
standard. Nothing here has been evaluated by anybody but the maintainer.

## What is aimed for

- **Keyboard.** Everything can be reached and used without a mouse, the control that has the
  focus can be seen, and nothing traps it.
- **Screen readers.** Every control has a name that says what it does, and a group of controls
  has a name for the group.
- **Text size and scaling.** The window follows the size of text and the display scaling the
  operating system is set to, and stays usable at twice the ordinary size.
- **Colour.** Colour is never the only thing that says something, and what is coloured can still
  be read in a high contrast theme and in both the light and the dark one.
- **The command line and the logs.** A failure exits with a code that is not zero, and a problem
  is named in words.

## What has been checked

Checked means tried by the maintainer. Each line says how.

| | State |
| --- | --- |
| Light and dark themes | In use on Windows 11 and Windows 10. Tick boxes that could hardly be seen in the dark on Windows 10 were given an outline. |
| Names for screen readers | The lists, entry boxes and choices in the bar, the panes and the dialogs are given names in the code. Not yet heard through a screen reader. |
| High contrast theme | Not yet checked. |
| Display scaling | Not yet checked at 200 %. |
| Large text | The fixed-pitch font and the width of boxes follow the system's text size. Not yet tried with text turned up. |
| Colour as the only signal | Not yet gone through. See *Known limitations*. |
| Keyboard only | Not yet checked. |
| Screen reader | Not yet checked, with any of them. |
| Linux | pyflashgui runs and is tested there. Not checked for any of the above. |

## Known limitations

- In the **Event Log**, a warning or an error is told apart from an ordinary line by its colour
  alone; an error is bold as well.
- The **Pin** and **Detach** buttons on a floating pane cannot be reached with the keyboard.

If you find another, please report it: this list is as long as what has been looked for.

## Reporting a barrier

Open an issue with the
[accessibility form](https://github.com/davhodg/pyflashgui/issues/new?template=accessibility.yml).
It asks what you were trying to do, what happened, and what you were using: the operating
system, and the text size, theme or assistive technology where it matters. A screenshot helps
and is not required. Nobody is asked about a disability, and nobody needs to say why they work
the way they do.

A barrier is ranked by how far it stops the work:

- **Critical** -- something cannot be done at all.
- **Serious** -- it can be done, with difficulty or by a way round.
- **Moderate** -- it is harder than it should be.
- **Minor** -- it is a nuisance.

## What happens to a report

pyflashgui is looked after by one person in their own time, so no date is promised. What is
promised is that every report is read and answered, that the answer says what is known and what
will be done, that a way round is given where there is one, and that you are asked whether a fix
works before the issue is closed. A report of a barrier is taken as something learned about the
program, not as a complaint.

## For contributors

A change to what is on screen keeps to these:

- **No font and no size in pixels written into a pane.** The fixed-pitch font and the width of a
  box come from `pyflashgui/ui/fonts.py`, which follows the system's text size.
- **Colour is not the only signal.** What a colour says is also said by a word, a mark or a
  tooltip.
- **A new control can be reached with the keyboard and has a name.** A button that is a symbol
  has an accessible name as well as a tooltip.
- **What is pressed often is a button; what is done once is in a menu.** A row of buttons wider
  than the pane is the commonest way a pane stops fitting at large text.

Tried with the text size turned up, and with the keyboard alone, before it is sent.

## Who looks after this

The maintainer, [@davhodg](https://github.com/davhodg), who answers the reports and keeps this
page in step with the program. Suggestions for the page itself are welcome as an issue or a pull
request.
