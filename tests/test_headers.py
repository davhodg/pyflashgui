# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 davhodg
"""Every Python file says which licence it is under, and names its holder.

Checked here because a header is exactly the kind of thing a new file is
created without.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APACHE = ("# SPDX-License-Identifier: Apache-2.0", "# SPDX-FileCopyrightText: 2026 davhodg")
#: Generated, installed or somebody else's -- not ours to stamp.
SKIPPED = {".venv", ".git", "dist", "work", "lib", "__pycache__", ".pytest_cache", ".ruff_cache"}


#: Where pyflashgui's own Python lives. A file somebody has just made here is
#: checked before it is ever committed, which is when a header gets forgotten.
OURS = ("pyflashgui", "tests", "build")


def _git(*args: str) -> list[str] | None:
    """What git lists, or None where there is no git or no checkout to ask."""
    try:
        said = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [line for line in said.stdout.splitlines() if line]


def sources() -> list[Path]:
    """The Python files that are this repository's.

    What git tracks, and what is new and not ignored in the folders the code
    lives in. Not every ``.py`` under the folder: a scratch file left at the
    top of somebody's checkout is not pyflashgui's, and failed a build for
    having no licence header. Without git -- an unpacked source archive --
    it is every file there is, as it used to be.
    """
    tracked = _git("ls-files", "*.py")
    if tracked is None:
        return _walked()
    new = _git("ls-files", "--others", "--exclude-standard", "*.py") or []
    wanted = set(tracked) | {name for name in new if name.split("/")[0] in OURS}
    return sorted(Path(name) for name in wanted if (ROOT / name).is_file())


def _walked() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if SKIPPED & set(rel.parts):
            continue
        # A folder a tool keeps for itself -- a second checkout of this
        # repository among them -- is not part of this one.
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        if any(part.endswith(".egg-info") or part.startswith("bdist.") for part in rel.parts):
            continue
        found.append(rel)
    return found


def head(rel: Path, lines: int = 6) -> list[str]:
    with open(ROOT / rel, encoding="utf-8") as f:
        return [f.readline().rstrip("\r\n") for _ in range(lines)]


def test_there_are_files_to_check():
    """A walk that found nothing would pass everything below."""
    assert len(sources()) > 40


def test_pyflashgui_code_is_apache_and_names_its_holder():
    wrong = [str(rel) for rel in sources() if tuple(head(rel, 2)) != APACHE]
    assert not wrong, f"missing or wrong Apache-2.0 header: {wrong}"


def test_every_licence_named_is_shipped_and_declared():
    assert (ROOT / "LICENSE").is_file()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["license"] == "Apache-2.0"
