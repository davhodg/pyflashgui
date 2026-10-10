<!-- Thank you for contributing. The policy is in CONTRIBUTING.md; this is its short form. -->

## What this changes, and why

<!-- One change per pull request. Link the issue it closes, if there is one: "Closes #123". -->

## Checklist

- [ ] An issue was opened first, if this is a large change
- [ ] Tests come with it, and a fix has one that fails without it
- [ ] The full suite and the linter pass (`pytest -n auto tests`, `ruff check`, `ruff format --check`)
- [ ] A line in `pyflashgui/help/changelog.md` under *Unreleased*, if a user would notice it
- [ ] The help page is updated, if the behaviour it describes changed
- [ ] Anything that can disturb equipment asks first, through pyflashgui's confirmations
- [ ] Any new dependency is explained here and is not GPL-only
- [ ] No proprietary material: no company firmware images, identifiers or code

## Tested on

<!-- Windows, Linux or macOS; the probe and target, if real hardware was used. -->
