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

Lenient is not the same as obvious, though. Every file we write carries the
rules as an HTML comment (GUIDANCE below) and an empty ``## Todos`` heading,
because whoever edits the file next — a person on GitHub, or an agent handed
the repo — sees only the file, not this module. Comments are stripped on the
way back in, so the block round-trips without ever reaching the board.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VALID_STATUSES = ("idea", "active", "paused", "done")

_TODO_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.*\S)\s*$")
_TODOS_HEADING_RE = re.compile(r"^##\s+to-?dos\s*$", re.IGNORECASE)
# Whole-line comments take their newline with them, so removing the guidance
# block doesn't leave a blank gap behind in the notes.
_COMMENT_BLOCK_RE = re.compile(
    r"^[ \t]*<!--.*?-->[ \t]*\r?\n?", re.DOTALL | re.MULTILINE
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

GUIDANCE = """\
<!--
IdeaBRD parses this file. It is the source of truth for this idea's tile:
the app re-reads it on every open and commits its own edits back here, so
the shape below matters more than it looks. Anything the parser
(backend/app/ideafile.py) can't read is dropped silently.

  frontmatter  status: one of idea, active, paused, done. progress: 0-100.
               Any other key is ignored.
  # heading    The idea title (first H1).
  prose        Everything outside the Todos section becomes the tile's
               notes, shown on the board — so keep it short. Documentation
               written here is published, not filed away.
  ## Todos     That heading exactly (or "## To-Dos"); "## ToDo", "## TODO"
               and "## Tasks" do not match and the whole list is lost.
               Inside it, only "- [ ] open" / "- [x] done" lines survive:
               sub-headings and blank-line grouping are discarded, and a
               wrapped item is cut at the line break, so keep each to-do on
               one line. The next "## " heading ends the list.

To-dos are matched to the board by exact text, so rewording one replaces it
rather than editing it in place — expect a checked item to come back
unchecked if you reword it.

HTML comments are stripped on read, so this block never reaches the board.
-->"""


def _strip_comments(body: str) -> str:
    return _COMMENT_RE.sub("", _COMMENT_BLOCK_RE.sub("", body))


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
    guidance: bool = True,
) -> str:
    """Render the idea as IDEA.md.

    The ``## Todos`` heading is always written, empty list or not: a heading
    that is already there gets filled in, where a missing one gets invented
    under whatever name the editor guesses (and then parsed as notes).
    """
    lines = [
        "---",
        f"status: {status}",
        f"progress: {progress}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if guidance:
        lines += [GUIDANCE, ""]
    if notes.strip():
        lines += [notes.strip(), ""]
    lines += ["## Todos", ""]
    lines += [f"- [{'x' if done else ' '}] {text}" for text, done in todos]
    if todos:
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
    # Strip comments before anything reads the body: the guidance block spans
    # lines and quotes "- [ ]" examples, which would otherwise land in notes or
    # be picked up as to-dos. Frontmatter is parsed first so a "---" inside a
    # comment can't move the fence.
    body = _strip_comments("\n".join(lines[body_start:])).splitlines()

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
    for line in body:
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
