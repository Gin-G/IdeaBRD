"""The board, read from and written to its git repository.

This is what replaces the database. There is no second copy of an idea: the
repo is the board, the same way it already is for the Android app, and this
module is the server's half of that — the equivalent of the app's `BoardStore`,
speaking to GitHub's API rather than to a checkout, because a server that keeps
no clone keeps nothing to lose or to back up.

Two things are worth understanding before reading further.

**Ideas are slugs; the API is integers.** Git has no autoincrement, and giving
it one would mean a manifest — the one file every writer is guaranteed to
conflict on. So an idea's id is hashed from its slug, by the same FNV-1a the
Android app and the browser build already use, which means the three agree on
what `/api/ideas/12345` refers to without ever having spoken.

**Reads are cached against the commit.** Listing a board is one tree request
plus a blob per idea, which is far too much to repeat on every poll. The cache
is keyed on the branch's head, so it is exactly as stale as the repo is old:
one cheap request confirms the head, and everything else is served from memory
until somebody commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.boardrepo import IDEAS_DIR, idea_file_path
from app.github import get_blob, get_ref, get_tree
from app.ideafile import ParsedIdeaFile, parse_idea_file

DEFAULT_BRANCH = "main"

# FNV-1a, 32-bit, folded to 31 so the result is a positive integer everywhere.
_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193
_MASK32 = 0xFFFFFFFF


def id_for(slug: str) -> int:
    """A stable positive id for a slug.

    Deliberately the same arithmetic as `idFor` in the browser build: the id
    goes in URLs, so a board opened on a phone and the same board opened in a
    browser have to arrive at the same number for the same idea.
    """
    hashed = _FNV_OFFSET
    for char in slug:
        hashed = (hashed ^ ord(char)) & _MASK32
        hashed = (hashed * _FNV_PRIME) & _MASK32
    return (hashed >> 1) or 1


@dataclass
class Tile:
    """One idea as the repository has it."""

    slug: str
    file: ParsedIdeaFile
    logo_path: str | None = None
    logo_sha: str | None = None

    @property
    def id(self) -> int:
        return id_for(self.slug)


@dataclass
class Board:
    """A board at one commit."""

    repo: str
    branch: str
    commit: str | None
    tiles: list[Tile] = field(default_factory=list)

    def by_slug(self, slug: str) -> Tile | None:
        return next((t for t in self.tiles if t.slug == slug), None)

    def by_id(self, idea_id: int) -> Tile | None:
        return next((t for t in self.tiles if t.id == idea_id), None)


# (repo, branch, commit) -> Board. Bounded by hand: a board is small, but a
# process that ran for a month should not hold every commit it ever saw.
_cache: dict[tuple[str, str, str], Board] = {}
_CACHE_LIMIT = 64


def clear_cache() -> None:
    """Forget everything. For tests, and for a write that just moved the head."""
    _cache.clear()


def _remember(board: Board) -> Board:
    if board.commit is None:
        return board
    if len(_cache) >= _CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[(board.repo, board.branch, board.commit)] = board
    return board


def _slug_of(path: str) -> str | None:
    """`ideas/<slug>/IDEA.md` -> `<slug>`, and nothing else."""
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == IDEAS_DIR and parts[2] == "IDEA.md":
        return parts[1]
    return None


async def read_board(
    repo: str,
    branch: str = DEFAULT_BRANCH,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Board:
    """Every idea on the board, at the branch's current head."""
    head = await get_ref(repo, branch, token=token, client=client)
    if head is None:
        # A repo with no commits is a board with no ideas, not an error: it is
        # what a board looks like in the moment after it is created.
        return Board(repo=repo, branch=branch, commit=None)

    cached = _cache.get((repo, branch, head))
    if cached is not None:
        return cached

    tree = await get_tree(repo, head, token=token, client=client)
    board = Board(repo=repo, branch=branch, commit=head)

    logos: dict[str, tuple[str, str]] = {}
    for path, sha in tree.items():
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == IDEAS_DIR and parts[2].startswith("idea_logo."):
            logos[parts[1]] = (path, sha)

    for path, sha in sorted(tree.items()):
        slug = _slug_of(path)
        if slug is None:
            continue
        raw = await get_blob(repo, sha, token=token, client=client)
        logo = logos.get(slug)
        board.tiles.append(
            Tile(
                slug=slug,
                file=parse_idea_file(raw.decode("utf-8", "replace")),
                logo_path=logo[0] if logo else None,
                logo_sha=logo[1] if logo else None,
            )
        )

    board.tiles.sort(key=lambda t: (t.file.rank or "", t.slug))
    return _remember(board)


async def read_idea(
    repo: str,
    slug: str,
    branch: str = DEFAULT_BRANCH,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Tile | None:
    """One idea, without reading the rest of the board."""
    board = await read_board(repo, branch, token=token, client=client)
    return board.by_slug(slug)


def idea_path(slug: str) -> str:
    """Where an idea's file lives, for callers that write one."""
    return idea_file_path(slug)
