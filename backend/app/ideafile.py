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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from app.rank import is_rank
from app.repo_ref import InvalidRepoRef, normalize_repo

VALID_STATUSES = ("idea", "active", "paused", "done")

# Board-level frontmatter, written only into a board repo's copy of an idea —
# see app.boardrepo. A linked repo's own IDEA.md must never carry these: rank
# and colour belong to whoever's board the tile sits on, and a shared idea sits
# on several boards at different positions.
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

_TODO_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.*\S)\s*$")
_TODOS_HEADING_RE = re.compile(r"^##\s+to-?dos\s*$", re.IGNORECASE)
# Trailing "(#12)" binds the item to a GitHub issue. Requiring a non-empty
# remainder keeps a bare "- [ ] (#12)" as literal text rather than a link to
# an issue with no to-do attached.
_ISSUE_SUFFIX_RE = re.compile(r"^(.+?)\s*\(#(\d+)\)$")
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
  (#12)        A to-do ending in an issue reference is backed by that issue
               in this repo. The issue wins: its title becomes the to-do's
               text and its open/closed state the checkbox, both here and on
               the board. Ticking the box in the app closes the issue.

Working in this repo? This file is the to-do list — use it rather than
starting a parallel one. Tick items off as you finish them, add new ones as
you find them, and keep status/progress honest: a TODO.md, a plan in a chat
window or a checklist in a commit message is invisible to everyone reading
the board. For work worth assigning, discussing, or writing up at length,
open a real issue and append its "(#12)" to the line — the item is then
tracked by number instead of text, and the issue holds the detail this file
has no room for (prose here is published to the board, not filed away).

To-dos without an issue are matched to the board by exact text, so rewording
one replaces it rather than editing it in place — expect a checked item to
come back unchecked if you reword it. Issue-backed to-dos are matched by
number instead, so keep the "(#12)" and reword freely; drop the reference and
the item becomes an ordinary to-do again (the issue itself is left alone).

HTML comments are stripped on read, so this block never reaches the board.
-->"""


def _strip_comments(body: str) -> str:
    return _COMMENT_RE.sub("", _COMMENT_BLOCK_RE.sub("", body))


def _split_issue_ref(text: str) -> tuple[str, int | None]:
    """Split "Build MVP (#12)" into ("Build MVP", 12); no suffix means no issue."""
    m = _ISSUE_SUFFIX_RE.match(text)
    if not m:
        return text, None
    return m.group(1), int(m.group(2))


class ParsedTodo(NamedTuple):
    text: str
    done: bool
    # Issue number backing this item, from a trailing "(#12)".
    issue: int | None = None


# Callers may hand render_idea_file plain (text, done) pairs; the issue is optional.
TodoInput = ParsedTodo | tuple[str, bool] | tuple[str, bool, int | None]


def _as_todo(item: TodoInput) -> ParsedTodo:
    return item if isinstance(item, ParsedTodo) else ParsedTodo(*item)


@dataclass
class ParsedIdeaFile:
    title: str | None = None
    notes: str = ""
    status: str | None = None
    progress: int | None = None
    # Board-level keys; None when the file is a linked repo's own IDEA.md,
    # which carries the idea but not anyone's board position for it.
    color: str | None = None
    rank: str | None = None
    repo: str | None = None
    # In file order.
    todos: list[ParsedTodo] = field(default_factory=list)


def render_idea_file(
    *,
    title: str,
    notes: str,
    status: str,
    progress: int,
    todos: Sequence[TodoInput],
    guidance: bool = True,
    color: str | None = None,
    rank: str | None = None,
    repo: str | None = None,
) -> str:
    """Render the idea as IDEA.md.

    The ``## Todos`` heading is always written, empty list or not: a heading
    that is already there gets filled in, where a missing one gets invented
    under whatever name the editor guesses (and then parsed as notes).

    ``color``, ``rank`` and ``repo`` are omitted unless given, so the file the
    board repo writes can carry a tile's position while the same renderer keeps
    writing linked repos exactly as it did before.
    """
    lines = [
        "---",
        f"status: {status}",
        f"progress: {progress}",
    ]
    if color is not None:
        # Quoted because "#..." opens a comment in YAML, and a board file that
        # only our own lenient parser can read is a trap for anything else.
        lines.append(f'color: "{color}"')
    if rank is not None:
        lines.append(f'rank: "{rank}"')
    if repo is not None:
        lines.append(f"repo: {repo}")
    lines += [
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
    items = [_as_todo(t) for t in todos]
    lines += [
        f"- [{'x' if item.done else ' '}] {item.text}"
        + (f" (#{item.issue})" if item.issue else "")
        for item in items
    ]
    if items:
        lines.append("")
    return "\n".join(lines)


def render_reference_file(*, repo: str, rank: str, color: str) -> str:
    """A board entry for an idea whose content lives in its own repository.

    The board records that the idea is on it and where it sits; the repo named
    here holds the idea. Copying the notes and to-dos in as well would put the
    same text in two places under two histories, which is the drift this layout
    exists to avoid — so the body is a pointer, derived entirely from ``repo``,
    and there is nothing here that can fall out of date.
    """
    url = f"https://github.com/{repo}"
    return "\n".join(
        [
            "---",
            f'color: "{color}"',
            f'rank: "{rank}"',
            f"repo: {repo}",
            "---",
            "",
            f"# {repo}",
            "",
            f"This idea lives in [{repo}]({url}).",
            "",
            "This board records which ideas are on it and where each one lives.",
            f"The idea itself — its notes, progress and to-dos — is in that",
            "repository's own IDEA.md, which is the copy that counts.",
            "",
        ]
    )


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
    # Board-level keys are validated and otherwise dropped, in keeping with the
    # rest of the parser: a hand-edited colour or rank that can't be used should
    # cost that one field, not the file.
    if _COLOR_RE.match(fm.get("color", "")):
        parsed.color = fm["color"].lower()
    if is_rank(fm.get("rank", "")):
        parsed.rank = fm["rank"]
    if "repo" in fm:
        try:
            parsed.repo = normalize_repo(fm["repo"])
        except InvalidRepoRef:
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
                text, issue = _split_issue_ref(m.group(2))
                parsed.todos.append(
                    ParsedTodo(text, m.group(1).lower() == "x", issue)
                )
            # non-item lines inside the Todos section are ignored
            continue
        note_lines.append(line)

    parsed.notes = "\n".join(note_lines).strip()
    return parsed
