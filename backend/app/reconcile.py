"""Compare the board repo against the database and report what disagrees.

The plan is to stop writing the board to Postgres and read it from git instead.
That is a decision, and a decision needs evidence: "the publisher's tests pass"
says the code does what it was written to do, not that the repo currently holds
the board. This is the check that says so — every idea, from both sides, and
the fields that differ.

It is deliberately read-only. Nothing here writes, publishes or repairs; the
report is meant to be read before anyone chooses to do any of those. Ideas are
compared by their *parsed* content rather than their bytes, so a difference is
named ("status", "todos") instead of being reported as "the file changed".

Fetching is kept honest by the same trick the publisher uses: the desired
file's git blob sha is computed locally and compared against the sha the tree
listing already carries, so an idea that matches costs no request at all and
only genuine differences are downloaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.boardrepo import IDEAS_DIR, IDEA_FILE, idea_file_path
from app.github import GitHubError, get_blob, get_ref, get_tree
from app.ideafile import ParsedIdeaFile, parse_idea_file
from app.models import User
from app.publisher import (
    DEFAULT_BRANCH,
    assign_identity,
    blob_sha,
    board_token,
    build_tree,
    load_board,
)

# Fields compared between the two copies of an idea, in the order a reader
# would want them: what the idea says first, where the board puts it last.
COMPARED = ("title", "notes", "status", "progress", "todos", "color", "rank", "repo")

SAME = "same"
DIFFERS = "differs"
MISSING_IN_REPO = "missing_in_repo"
MISSING_IN_BOARD = "missing_in_board"


@dataclass
class Entry:
    slug: str
    state: str
    title: str | None = None
    idea_id: int | None = None
    differences: list[str] = field(default_factory=list)


@dataclass
class Report:
    repo: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    in_sync: bool = False
    moved: bool = False
    entries: list[Entry] = field(default_factory=list)
    error: str | None = None


def compare(ours: ParsedIdeaFile, theirs: ParsedIdeaFile) -> list[str]:
    """Field names on which the two copies of an idea disagree."""
    out = []
    for name in COMPARED:
        if getattr(ours, name) != getattr(theirs, name):
            out.append(name)
    return out


def _slug_of(path: str) -> str | None:
    """The idea directory a repo path belongs to, or None if it isn't one."""
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == IDEAS_DIR and parts[2] == IDEA_FILE:
        return parts[1]
    return None


async def reconcile_board(
    session: AsyncSession, user: User, *, client=None
) -> Report:
    """Diff the user's board against its repo, without changing either."""
    if not user.board_repo:
        return Report(error="No board repo configured")
    repo = user.board_repo
    branch = user.board_branch or DEFAULT_BRANCH
    token = await board_token(session, user)
    report = Report(repo=repo, branch=branch)

    try:
        head = await get_ref(repo, branch, token=token, client=client)
        if head is None:
            return Report(
                repo=repo,
                branch=branch,
                error=f"{repo} has no commits on {branch!r} yet",
            )
        report.commit_sha = head
        report.moved = bool(user.board_commit_sha) and head != user.board_commit_sha
        tree = await get_tree(repo, head, token=token, client=client)

        tiles = assign_identity(await load_board(session, user))
        desired = await build_tree(session, tiles)

        seen: set[str] = set()
        for tile in tiles:
            slug = tile.slug or ""
            seen.add(slug)
            path = idea_file_path(slug)
            want = desired[path]
            have = tree.get(path)
            entry = Entry(
                slug=slug, state=SAME, title=tile.idea.title, idea_id=tile.idea.id
            )
            if have is None:
                entry.state = MISSING_IN_REPO
            elif have != blob_sha(want):
                entry.state = DIFFERS
                entry.differences = compare(
                    parse_idea_file(want.decode("utf-8")),
                    parse_idea_file(
                        (
                            await get_blob(repo, have, token=token, client=client)
                        ).decode("utf-8", "replace")
                    ),
                )
            # The tile image is part of the idea even though it isn't in the
            # file, so a repo whose logo has drifted is not "the same".
            logos = [
                p
                for p in desired
                if p != path and p.startswith(f"{IDEAS_DIR}/{slug}/")
            ]
            if entry.state != MISSING_IN_REPO and any(
                tree.get(p) != blob_sha(desired[p]) for p in logos
            ):
                entry.state = DIFFERS
                entry.differences.append("logo")
            report.entries.append(entry)

        for path, sha in sorted(tree.items()):
            slug = _slug_of(path)
            if slug is None or slug in seen:
                continue
            parsed = parse_idea_file(
                (await get_blob(repo, sha, token=token, client=client)).decode(
                    "utf-8", "replace"
                )
            )
            report.entries.append(
                Entry(slug=slug, state=MISSING_IN_BOARD, title=parsed.title)
            )
    except GitHubError as exc:
        return Report(repo=repo, branch=branch, error=str(exc))

    report.in_sync = not report.moved and all(
        e.state == SAME for e in report.entries
    )
    return report
