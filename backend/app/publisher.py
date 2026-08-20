"""Publish a whole board into its git repo as files.

This is the second copy of the board, written so the git-only client has
something to read before anything depends on it. Postgres stays authoritative
throughout: publishing never reads back into the database, so a broken publish
costs a commit, not a board.

What lands is the layout in ``app.boardrepo`` — ``ideas/<slug>/IDEA.md`` plus
its logo, and a ``.ideabrd`` marker naming the format version. Each file is the
same IDEA.md the app already writes, with the board-level keys (``rank``,
``color``, ``repo``) that only a board copy carries.

Three things this deliberately does not do:

**Commit per file.** A board is many files and one intent. Blobs go up, then a
single tree, then one commit — so a publish either lands whole or not at all,
and the history reads as "the board changed", not twenty renames.

**Write what hasn't changed.** Every desired file's blob sha is computed
locally and compared against the tree already in the repo. An unchanged board
publishes nothing and makes no commit. This is what makes fractional ranks pay
off: move one tile and one file is written.

**Touch anything outside the board.** Only ``.ideabrd`` and paths under
``ideas/`` are ever written or removed, and a repo that already has content but
no marker is refused until the user opts in — the same gate ``app.gitsync`` puts
in front of seeding someone's repo with an IDEA.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.boardrepo import (
    FORMAT_VERSION,
    IDEAS_DIR,
    MARKER_FILE,
    idea_file_path,
    logo_path,
    unique_slug,
)
from app.github import (
    FILE_MODE,
    GitHubError,
    create_blob,
    create_commit,
    create_tree,
    get_ref,
    get_tree,
    put_file,
    update_ref,
)
from app.ideafile import ParsedTodo, render_idea_file
from app.logos import logo_path_for
from app.models import Idea, IdeaCollaborator, IdeaLogo, Identity, User
from app.rank import repair

DEFAULT_BRANCH = "main"
COMMIT_MESSAGE = "Publish board (via IdeaBRD)"
SEED_MESSAGE = "Create board (via IdeaBRD)"


@dataclass
class BoardTile:
    """One tile as it will be written: the idea, plus where it sits on *this* board."""

    idea: Idea
    slug: str | None
    rank: str | None
    # The collaborator row this tile came from, when the idea is someone else's.
    membership: IdeaCollaborator | None = None
    position: int = 0

    @property
    def shared(self) -> bool:
        return self.membership is not None


@dataclass
class PublishResult:
    committed: bool = False
    commit_sha: str | None = None
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    needs_opt_in: bool = False
    error: str | None = None


def blob_sha(data: bytes) -> str:
    """Git's own hash for a file's contents.

    Computing it here is what lets a publish skip unchanged files without
    downloading any of them: the tree listing already carries this sha.
    """
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


async def board_token(session: AsyncSession, user: User) -> str | None:
    """The user's own GitHub token — a board repo is published as its owner."""
    return await session.scalar(
        select(Identity.github_token).where(
            Identity.user_id == user.id,
            Identity.provider == "github",
            Identity.github_token.is_not(None),
        )
    )


async def load_board(session: AsyncSession, user: User) -> list[BoardTile]:
    """Every tile on the user's board, owned and shared, in the order they see.

    Owned and shared tiles share one position namespace (see list_ideas), so
    they are merged before anything is ranked.
    """
    owned = (
        (
            await session.execute(
                select(Idea)
                .where(Idea.user_id == user.id)
                .options(selectinload(Idea.todos))
            )
        )
        .scalars()
        .all()
    )
    shared = (
        await session.execute(
            select(IdeaCollaborator, Idea)
            .join(Idea, Idea.id == IdeaCollaborator.idea_id)
            .where(IdeaCollaborator.user_id == user.id)
            .options(selectinload(IdeaCollaborator.idea).selectinload(Idea.todos))
        )
    ).all()

    tiles = [
        BoardTile(idea=i, slug=i.slug, rank=i.rank, position=i.position) for i in owned
    ]
    tiles += [
        BoardTile(
            idea=idea,
            slug=member.slug,
            rank=member.rank,
            membership=member,
            position=member.position,
        )
        for member, idea in shared
    ]
    # Position is what the board is ordered by everywhere else (see list_ideas),
    # so it is the order published. Rank is a projection of it, not a rival.
    tiles.sort(key=lambda t: (t.position, t.idea.id))
    return tiles


def assign_identity(tiles: list[BoardTile]) -> list[BoardTile]:
    """Fill in missing slugs and repair ranks, in board order.

    Slugs are unique across the whole board, not per owner: a shared idea can
    arrive at a board that already uses its directory name. Ranks are repaired
    against the board's position order rather than reassigned, so a settled
    board publishes no changes at all and a single drag rewrites a single rank.
    """
    tiles = sorted(tiles, key=lambda t: (t.position, t.idea.id))
    taken = {t.slug for t in tiles if t.slug}
    for tile in tiles:
        if not tile.slug:
            tile.slug = unique_slug(tile.idea.title or "", taken)
            taken.add(tile.slug)
    for tile, rank in zip(tiles, repair([t.rank for t in tiles])):
        tile.rank = rank
    return tiles


def render_tile(tile: BoardTile) -> str:
    """The IDEA.md for one tile, carrying the board-level keys a board copy owns."""
    idea = tile.idea
    todos = sorted(idea.todos, key=lambda t: (t.position, t.id))
    return render_idea_file(
        title=idea.title,
        notes=idea.notes,
        status=idea.status,
        progress=idea.progress,
        todos=[ParsedTodo(t.text, t.done, t.github_issue_number) for t in todos],
        color=idea.color,
        rank=tile.rank,
        repo=idea.github_repo,
    )


def marker_content() -> bytes:
    """The ``.ideabrd`` file, which is both a version and a claim on the layout."""
    return (
        json.dumps(
            {
                "version": FORMAT_VERSION,
                "layout": f"{IDEAS_DIR}/<slug>/IDEA.md",
                "generator": "IdeaBRD",
            },
            indent=2,
        )
        + "\n"
    ).encode()


async def build_tree(
    session: AsyncSession, tiles: list[BoardTile]
) -> dict[str, bytes]:
    """The complete set of files this board should be, path -> bytes."""
    files: dict[str, bytes] = {MARKER_FILE: marker_content()}
    for tile in tiles:
        assert tile.slug  # assign_identity ran first
        files[idea_file_path(tile.slug)] = render_tile(tile).encode()
        logo = await session.get(IdeaLogo, tile.idea.id)
        if logo is not None:
            name = logo_path_for(logo.content_type)
            files[logo_path(tile.slug, name)] = logo.data
    return files


def _managed(path: str) -> bool:
    """Whether a path in the repo belongs to the board and may be removed."""
    return path == MARKER_FILE or path.startswith(f"{IDEAS_DIR}/")


def diff(
    desired: dict[str, bytes], current: dict[str, str]
) -> tuple[dict[str, bytes], list[str]]:
    """Files to write and paths to remove, given the repo's current blob shas.

    Removals are confined to paths the board owns, so publishing into a repo
    that holds anything else leaves the rest of it alone.
    """
    writes = {
        path: data
        for path, data in desired.items()
        if current.get(path) != blob_sha(data)
    }
    removals = [p for p in current if _managed(p) and p not in desired]
    return writes, sorted(removals)


async def publish_board(
    session: AsyncSession,
    user: User,
    *,
    opt_in: bool = False,
    client=None,
) -> PublishResult:
    """Write the user's board to their board repo as one commit.

    Best-effort in the same spirit as app.gitsync: a GitHub failure comes back
    as a message rather than an exception, since the board itself is fine.
    """
    if not user.board_repo:
        return PublishResult(error="No board repo configured")
    token = await board_token(session, user)
    repo = user.board_repo
    branch = user.board_branch or DEFAULT_BRANCH

    try:
        head = await get_ref(repo, branch, token=token, client=client)
        if head is None:
            # A repo with no commits at all refuses every git data write with
            # "Git Repository is empty" — blobs included, so there is no way to
            # build the first tree. The contents API does work on one, so the
            # marker goes up through that and the board publishes on top of it.
            await put_file(
                repo,
                MARKER_FILE,
                marker_content(),
                SEED_MESSAGE,
                token=token,
                client=client,
            )
            head = await get_ref(repo, branch, token=token, client=client)
            if head is None:
                return PublishResult(
                    error=f"Could not find branch {branch!r} after creating the board"
                )
        current = await get_tree(repo, head, token=token, client=client)

        # Same gate app.gitsync puts in front of seeding a repo: a repo with
        # content that isn't already a board is never written to unprompted.
        if current and MARKER_FILE not in current and not opt_in:
            return PublishResult(needs_opt_in=True)

        tiles = assign_identity(await load_board(session, user))
        desired = await build_tree(session, tiles)
        writes, removals = diff(desired, current)

        # Identity is persisted whether or not anything is committed: a slug
        # assigned here has to be the same slug next time, or the next publish
        # renames directories that are already in the history.
        for tile in tiles:
            target = tile.membership if tile.shared else tile.idea
            target.slug, target.rank = tile.slug, tile.rank
        await session.commit()

        if not writes and not removals:
            return PublishResult(committed=False)

        entries = [
            {
                "path": path,
                "mode": FILE_MODE,
                "type": "blob",
                "sha": await create_blob(repo, data, token=token, client=client),
            }
            for path, data in sorted(writes.items())
        ]
        entries += [
            {"path": path, "mode": FILE_MODE, "type": "blob", "sha": None}
            for path in removals
        ]
        tree = await create_tree(
            repo, entries, base_tree=head, token=token, client=client
        )
        commit = await create_commit(
            repo, COMMIT_MESSAGE, tree, [head] if head else [], token=token, client=client
        )
        await update_ref(repo, branch, commit, token=token, client=client)
    except GitHubError as exc:
        return PublishResult(error=str(exc))

    user.board_commit_sha = commit
    user.board_published_at = datetime.now(timezone.utc)
    await session.commit()
    return PublishResult(
        committed=True,
        commit_sha=commit,
        written=sorted(writes),
        removed=removals,
    )
