"""Rewrite the shared golden IDEA.md fixtures from the Python renderer.

Run after a deliberate change to the file format:

    cd backend && python -m tests.regenerate_golden

The Kotlin suite then fails until the port is brought back into line, which is
exactly the signal wanted — the two renderers agreeing is the thing the
fixtures exist to prove.
"""

from __future__ import annotations

from pathlib import Path

from app.ideafile import ParsedTodo, render_idea_file, render_reference_file

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "idea-files"


def cases() -> dict[str, str]:
    return {
        "full.md": render_idea_file(
            title="My idea",
            notes="Some notes.\n\nMore notes, with a [link](https://example.com).",
            status="active",
            progress=60,
            todos=[
                ParsedTodo("set up repo", True),
                ParsedTodo("build MVP", False),
                ParsedTodo("ship it", False, 12),
            ],
        ),
        "minimal.md": render_idea_file(
            title="Fresh", notes="", status="idea", progress=0, todos=[], guidance=False
        ),
        "board.md": render_idea_file(
            title="On a board",
            notes="Kept in someone's board repo.",
            status="paused",
            progress=25,
            todos=[ParsedTodo("one", False)],
            color="#6366f1",
            rank="a0m",
        ),
        "reference.md": render_reference_file(
            repo="octocat/hello", rank="a0m", color="#ec4899"
        ),
        "public-board.md": render_idea_file(
            title="Shown off",
            notes="On the owner's public page.",
            status="active",
            progress=80,
            todos=[ParsedTodo("one", True)],
            color="#6366f1",
            rank="a0m",
            public=True,
        ),
        "site.md": render_idea_file(
            title="Runs somewhere",
            notes="Has a site it is happy to show.",
            status="active",
            progress=50,
            todos=[],
            guidance=False,
            site="https://runs.example.net",
            site_public=True,
        ),
        "public-reference.md": render_reference_file(
            repo="octocat/hello", rank="a0m", color="#ec4899", public=True
        ),
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, text in cases().items():
        (FIXTURES / name).write_text(text)
        print(f"wrote {FIXTURES / name}")


if __name__ == "__main__":
    main()
