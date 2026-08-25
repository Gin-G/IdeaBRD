"""The rendered file, pinned.

Two implementations write IDEA.md now — this one and the Kotlin port the phone
uses — and they have to write the *same* file, not two files that happen to
parse the same. A stray blank line is a diff on every idea the first time a
board is edited on the other device, and a merge conflict on the edit after
that.

The fixtures in `fixtures/idea-files/` are the contract. Both suites assert
against them; changing the format means regenerating them (see
`tests.regenerate_golden`) and updating the port until it agrees.
"""

from __future__ import annotations

import pytest

from app.ideafile import parse_idea_file
from tests.regenerate_golden import FIXTURES, cases


@pytest.mark.parametrize("name", sorted(cases()))
def test_renderer_matches_the_shared_fixture(name):
    expected = (FIXTURES / name).read_text()
    assert cases()[name] == expected, (
        f"{name} changed. If that was deliberate, run "
        "`python -m tests.regenerate_golden` and update the Kotlin port to match."
    )


@pytest.mark.parametrize("name", sorted(cases()))
def test_every_fixture_parses_back(name):
    """A file we write must be one we can read; the port is held to this too."""
    parsed = parse_idea_file((FIXTURES / name).read_text())
    assert parsed.title
    assert "<!--" not in parsed.notes
