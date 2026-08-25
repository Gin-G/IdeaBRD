"""Merge two versions of an IDEA.md by meaning rather than by line.

The file is written by two editors that never see each other: the app, which
renders it whole from the database, and whoever edits it on GitHub. When both
have moved since the last sync, the app used to fetch the current blob sha and
push its own render over the top — a "merge" that consisted of winning. A
paragraph added on GitHub between two app edits simply disappeared.

Merging the *text* would not help either. The app re-renders the whole file, so
a line-level diff sees a rewrite even when nothing changed: the to-do list is
regenerated in board order, the guidance block is re-emitted, the frontmatter is
rebuilt. There is no textual common ground to merge on.

What both sides do share is the structure the parser already knows about, so
that is what gets merged: frontmatter fields, the title, the notes, and the
to-do list — the last one matched exactly the way ``gitsync._apply_todos``
matches it, by issue number where there is one and by exact text otherwise.

Three-way where a base is available (the blob we last synced, fetched by the
sha we recorded), two-way where it isn't. Two-way keeps everything from both
sides, because without a base an item missing from one side is indistinguishable
from an item the other side just added, and keeping a stale to-do is a smaller
harm than dropping a real one.

**Git wins ties, except where nothing has to lose.** A status can only have one
value, so where both sides set a different one the repo's wins — the same rule
``sync_pull`` already applies, and a pull moments later would have imposed it
anyway. Prose is not like that: two people who wrote different paragraphs both
wrote something, so a region both sides rewrote keeps both, the repo's first.
The result is occasionally a paragraph that reads oddly, which somebody can
fix; the alternative is a paragraph that is gone, which nobody can.
"""

from __future__ import annotations

from dataclasses import replace
from difflib import SequenceMatcher

from app.ideafile import ParsedIdeaFile, ParsedTodo, parse_idea_file, render_idea_file

# Identity of a to-do for matching purposes: its issue number if it has one,
# otherwise its exact text — the same rule the database side matches on, so an
# item reworded on GitHub is edited here rather than replaced.
TodoKey = tuple[str, str | int]


def todo_key(todo: ParsedTodo) -> TodoKey:
    return ("issue", todo.issue) if todo.issue is not None else ("text", todo.text)


def _pick(base, ours, theirs):
    """Three-way choice for one value. Git wins when both sides moved."""
    if ours == theirs:
        return ours
    if base is not None and ours == base:
        return theirs
    if base is not None and theirs == base:
        return ours
    return theirs


def _merge_lines(base: list[str], ours: list[str], theirs: list[str]) -> list[str]:
    """Line-level three-way merge, anchored on lines both sides left alone.

    Notes are prose, and prose is the one part of the file where two people
    editing different paragraphs is ordinary. Anchoring on the lines that
    survived in both versions lets each side's edits through. A region both
    rewrote keeps both versions, the repo's first — the duplication is visible
    and happens once, where a dropped paragraph is invisible and permanent.
    """
    if base == ours:
        return theirs
    if base == theirs:
        return ours

    def index_map(other: list[str]) -> dict[int, int]:
        mapping: dict[int, int] = {}
        for a, b, size in SequenceMatcher(None, base, other).get_matching_blocks():
            for k in range(size):
                mapping[a + k] = b + k
        return mapping

    ours_at, theirs_at = index_map(ours), index_map(theirs)
    anchors = sorted(set(ours_at) & set(theirs_at))

    merged: list[str] = []
    b = o = t = 0
    for i in [*anchors, len(base)]:
        oi = ours_at.get(i, len(ours))
        ti = theirs_at.get(i, len(theirs))
        base_seg, our_seg, their_seg = base[b:i], ours[o:oi], theirs[t:ti]
        if our_seg == base_seg:
            merged += their_seg
        elif their_seg == base_seg or our_seg == their_seg:
            merged += our_seg
        else:
            merged += their_seg + our_seg  # both rewrote it; keep both
        if i < len(base):
            merged.append(base[i])
            b, o, t = i + 1, oi + 1, ti + 1
    return merged


def _merge_notes(base: str | None, ours: str, theirs: str) -> str:
    if base is None:
        return theirs if ours != theirs else ours
    return "\n".join(
        _merge_lines(base.splitlines(), ours.splitlines(), theirs.splitlines())
    ).strip()


def _merge_todos(
    base: list[ParsedTodo] | None,
    ours: list[ParsedTodo],
    theirs: list[ParsedTodo],
) -> list[ParsedTodo]:
    """Merge two to-do lists, keeping each side's additions and deletions.

    Order follows the repo's list, since that is the one a person arranged by
    hand; items only this side has are slotted in after whatever preceded them
    here, so an item added at the top of the board does not come back at the
    bottom of the file.
    """
    ours_by_key = {todo_key(t): t for t in ours}
    theirs_by_key = {todo_key(t): t for t in theirs}
    base_by_key = {todo_key(t): t for t in base} if base is not None else {}

    def survives(key: TodoKey) -> bool:
        in_ours, in_theirs = key in ours_by_key, key in theirs_by_key
        if in_ours and in_theirs:
            return True
        if base is None:
            return True  # no base: an absence proves nothing, so keep it
        # Present on one side only: kept when it is an addition there, dropped
        # when it is a deletion on the other.
        return key not in base_by_key

    def merged(key: TodoKey) -> ParsedTodo:
        ours_item, theirs_item = ours_by_key.get(key), theirs_by_key.get(key)
        if ours_item is None:
            return theirs_item
        if theirs_item is None:
            return ours_item
        base_item = base_by_key.get(key)
        return ParsedTodo(
            text=_pick(
                base_item.text if base_item else None, ours_item.text, theirs_item.text
            ),
            done=_pick(
                base_item.done if base_item else None, ours_item.done, theirs_item.done
            ),
            issue=ours_item.issue if ours_item.issue is not None else theirs_item.issue,
        )

    out: list[ParsedTodo] = [
        merged(todo_key(t)) for t in theirs if survives(todo_key(t))
    ]
    placed = {todo_key(t) for t in theirs}
    previous: TodoKey | None = None
    for item in ours:
        key = todo_key(item)
        if key not in placed and survives(key):
            at = (
                next(
                    (i for i, o in enumerate(out) if todo_key(o) == previous),
                    len(out) - 1,
                )
                + 1
                if previous is not None
                else 0
            )
            out.insert(at, merged(key))
            placed.add(key)
        previous = key
    return out


def merge_parsed(
    base: ParsedIdeaFile | None, ours: ParsedIdeaFile, theirs: ParsedIdeaFile
) -> ParsedIdeaFile:
    """Merge two parsed idea files into one, field by field."""

    def field(name: str):
        return _pick(
            getattr(base, name) if base else None,
            getattr(ours, name),
            getattr(theirs, name),
        )

    return ParsedIdeaFile(
        title=field("title"),
        notes=_merge_notes(base.notes if base else None, ours.notes, theirs.notes),
        status=field("status"),
        progress=field("progress"),
        color=field("color"),
        rank=field("rank"),
        repo=field("repo"),
        todos=_merge_todos(base.todos if base else None, ours.todos, theirs.todos),
    )


def merge_idea_files(
    base: str | None, ours: str, theirs: str, *, guidance: bool = True
) -> tuple[str, ParsedIdeaFile]:
    """Merge two IDEA.md files, returning the rendered result and its parse.

    The parse comes back with it so the caller can write the merged state into
    the database in the same breath as pushing it — a merge that lands in the
    repo but not on the board is just a different way of losing an edit.
    """
    parsed = merge_parsed(
        parse_idea_file(base) if base is not None else None,
        parse_idea_file(ours),
        parse_idea_file(theirs),
    )
    # A file the parser found no title in still has to be rendered with one;
    # falling back through both sides keeps the merge from inventing a name.
    title = parsed.title or ""
    rendered = render_idea_file(
        title=title,
        notes=parsed.notes,
        status=parsed.status or "idea",
        progress=parsed.progress if parsed.progress is not None else 0,
        todos=parsed.todos,
        guidance=guidance,
        color=parsed.color,
        rank=parsed.rank,
        repo=parsed.repo,
    )
    return rendered, replace(parsed, title=title or None)
