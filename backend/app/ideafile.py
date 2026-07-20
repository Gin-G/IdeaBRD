"""Render and parse IDEA.md — the git-side representation of an idea.

The file lives at the root of the linked repo and is the source of truth for
the idea's editable details:

    ---
    status: active
    progress: 60
    ---

    # Title

    Free-form markdown notes.

    ## Todos

    - [x] done item
    - [ ] open item

Parsing is deliberately lenient so hand-edits on GitHub don't break sync:
frontmatter, the H1 and the Todos section are all optional, and unknown
frontmatter keys are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VALID_STATUSES = ("idea", "active", "paused", "done")

_TODO_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.*\S)\s*$")
_TODOS_HEADING_RE = re.compile(r"^##\s+to-?dos\s*$", re.IGNORECASE)


@dataclass
class ParsedIdeaFile:
    title: str | None = None
    notes: str = ""
    status: str | None = None
    progress: int | None = None
    # (text, done) in file order
    todos: list[tuple[str, bool]] = field(default_factory=list)


def render_idea_file(
    *,
    title: str,
    notes: str,
    status: str,
    progress: int,
    todos: list[tuple[str, bool]],
) -> str:
    lines = [
        "---",
        f"status: {status}",
        f"progress: {progress}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if notes.strip():
        lines += [notes.strip(), ""]
    if todos:
        lines += ["## Todos", ""]
        lines += [f"- [{'x' if done else ' '}] {text}" for text, done in todos]
        lines.append("")
    return "\n".join(lines)


def _parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], int]:
    """Return ({key: value}, index of first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    fm: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fm, i + 1
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip().lower()] = value.strip().strip("'\"")
    # No closing fence — treat the whole thing as body.
    return {}, 0


def parse_idea_file(text: str) -> ParsedIdeaFile:
    lines = text.splitlines()
    fm, body_start = _parse_frontmatter(lines)

    parsed = ParsedIdeaFile()
    if fm.get("status") in VALID_STATUSES:
        parsed.status = fm["status"]
    if "progress" in fm:
        try:
            parsed.progress = max(0, min(100, int(float(fm["progress"]))))
        except ValueError:
            pass

    note_lines: list[str] = []
    in_todos = False
    for line in lines[body_start:]:
        if (
            parsed.title is None
            and line.startswith("# ")
            and not any(prior.strip() for prior in note_lines)
        ):
            parsed.title = line[2:].strip() or None
            note_lines.clear()  # drop blank lines that preceded the title
            continue
        if _TODOS_HEADING_RE.match(line.strip()):
            in_todos = True
            continue
        if in_todos:
            if line.startswith("## "):  # a later section ends the todo list
                in_todos = False
                note_lines.append(line)
                continue
            m = _TODO_RE.match(line)
            if m:
                parsed.todos.append((m.group(2), m.group(1).lower() == "x"))
            # non-item lines inside the Todos section are ignored
            continue
        note_lines.append(line)

    parsed.notes = "\n".join(note_lines).strip()
    return parsed
