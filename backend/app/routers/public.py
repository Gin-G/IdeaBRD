"""A board owner's public page: the ideas they chose to show, read from git.

``GET /api/public/{login}`` needs no sign-in. ``login`` is the owner's GitHub
login, the one name every board has, since a board repo can't exist without a
GitHub identity.

Everything here is read from the board repo, not the database: the tiles
flagged ``public: true``, and for a tile that links a repo, that repo's own
IDEA.md. Both can be private, so they are read with the owner's stored GitHub
OAuth token (``repo`` scope, granted at sign-in). This reads the owner's
private repos on behalf of anonymous visitors, so what leaves is deliberately
narrow:

- only tiles the owner flagged, and only on boards they own (the publisher
  never writes the flag onto a shared tile);
- the first paragraph of the notes, not the notes. IDEA.md notes are written
  for the board and routinely hold operational detail, like where secrets
  live, that a portfolio page must not publish. The first paragraph is the
  pitch by the format's own convention;
- to-do counts, not to-do text;
- a repo link only when the repo is public, and no repo name otherwise;
- the idea's ``site`` only when its IDEA.md also says ``site_public: true``.
  A site behind a login can sit on a public tile without being advertised,
  and nothing guesses a link out of the notes.

An owner, a board or an idea that doesn't exist and one that isn't public all
return the same 404, so the endpoint can't be used to probe for accounts.

A built page is cached for ``_TTL_SECONDS``. One view costs a ref check plus
two GitHub calls per linked idea, and a public URL gets traffic nobody chose.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.github import GitHubError, fetch_repo_meta, get_blob, get_file
from app.ideafile import ParsedIdeaFile, parse_idea_file
from app.models import Identity, User
from app.store import DEFAULT_BRANCH, Tile, read_board

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])

_TTL_SECONDS = 600
_SUMMARY_LIMIT = 600

_LOGO_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}


class PublicIdea(BaseModel):
    slug: str
    title: str
    status: str
    progress: int
    summary: str
    color: str | None = None
    todos_done: int
    todos_total: int
    # Only set when the repo is public. A private repo is neither linked nor
    # named.
    repo_url: str | None = None
    # The idea's site, only when its IDEA.md marks it site_public.
    site_url: str | None = None
    logo_url: str | None = None


class PublicBoard(BaseModel):
    login: str
    name: str | None = None
    ideas: list[PublicIdea]


@dataclass
class _Owner:
    login: str
    name: str | None
    token: str
    repo: str
    branch: str


_cache: dict[str, tuple[float, PublicBoard]] = {}


def clear_cache() -> None:
    _cache.clear()


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_EMPHASIS_RE = re.compile(r"(\*\*|__|`)")
def summarize(notes: str) -> str:
    """The first paragraph of the notes, as plain text.

    Markdown links keep their text and lose the URL, and bold and code markers
    go: the page renders this as text, and literal asterisks read as noise.
    """
    for block in re.split(r"\n\s*\n", notes.strip()):
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        text = " ".join(line.strip() for line in block.splitlines())
        text = _EMPHASIS_RE.sub("", _LINK_RE.sub(r"\1", text))
        if len(text) > _SUMMARY_LIMIT:
            text = text[: _SUMMARY_LIMIT].rsplit(" ", 1)[0] + "…"
        return text
    return ""


async def _owner(session: AsyncSession, login: str) -> _Owner:
    row = (
        await session.execute(
            select(Identity.github_login, Identity.github_token, User)
            .join(User, User.id == Identity.user_id)
            .where(
                Identity.provider == "github",
                func.lower(Identity.github_login) == login.lower(),
                Identity.github_token.is_not(None),
            )
        )
    ).first()
    if row is None or not row[2].board_repo:
        raise _not_found()
    canonical, token, user = row
    return _Owner(
        login=canonical,
        name=user.name,
        token=token,
        repo=user.board_repo,
        branch=user.board_branch or DEFAULT_BRANCH,
    )


async def _public_idea(
    owner: _Owner, tile: Tile, client: httpx.AsyncClient
) -> PublicIdea | None:
    content: ParsedIdeaFile = tile.file
    repo_url = None
    if tile.file.repo:
        # The board holds a stub; the idea lives in its own repo.
        try:
            found = await get_file(
                tile.file.repo, "IDEA.md", token=owner.token, client=client
            )
            meta = await fetch_repo_meta(tile.file.repo, token=owner.token, client=client)
        except GitHubError as exc:
            log.warning("public page %s: skipping %s: %s", owner.login, tile.slug, exc)
            return None
        if found is None:
            return None
        content = parse_idea_file(found[0])
        if meta is not None and not meta.private:
            repo_url = meta.html_url

    if not content.title:
        return None
    return PublicIdea(
        slug=tile.slug,
        title=content.title,
        status=content.status or "idea",
        progress=content.progress or 0,
        summary=summarize(content.notes),
        color=tile.file.color,
        todos_done=sum(1 for t in content.todos if t.done),
        todos_total=len(content.todos),
        repo_url=repo_url,
        site_url=content.site if content.site_public else None,
        logo_url=(
            f"/api/public/{owner.login}/logo/{tile.slug}" if tile.logo_path else None
        ),
    )


async def _build(owner: _Owner) -> PublicBoard:
    async with httpx.AsyncClient(
        base_url=settings.github_api_base, timeout=10.0
    ) as client:
        board = await read_board(
            owner.repo, owner.branch, token=owner.token, client=client
        )
        tiles = [t for t in board.tiles if t.file.public]
        ideas = await asyncio.gather(*(_public_idea(owner, t, client) for t in tiles))
    return PublicBoard(
        login=owner.login, name=owner.name, ideas=[i for i in ideas if i is not None]
    )


@router.get("/{login}", response_model=PublicBoard)
async def public_board(
    login: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    owner = await _owner(session, login)
    key = owner.login.lower()
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < _TTL_SECONDS:
        page = cached[1]
    else:
        try:
            page = await _build(owner)
        except GitHubError as exc:
            log.warning("public page %s: board unreadable: %s", owner.login, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="This board can't be read right now",
            ) from exc
        _cache[key] = (time.monotonic(), page)
    response.headers["Cache-Control"] = f"public, max-age={_TTL_SECONDS // 2}"
    return page


@router.get("/{login}/logo/{slug}")
async def public_logo(
    login: str,
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    owner = await _owner(session, login)
    try:
        board = await read_board(owner.repo, owner.branch, token=owner.token)
    except GitHubError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    tile = board.by_slug(slug)
    if tile is None or not tile.file.public or not tile.logo_path or not tile.logo_sha:
        raise _not_found()
    ext = tile.logo_path.rsplit(".", 1)[-1].lower()
    media_type = _LOGO_TYPES.get(ext)
    if media_type is None:
        raise _not_found()
    try:
        data = await get_blob(owner.repo, tile.logo_sha, token=owner.token)
    except GitHubError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    headers = {"Cache-Control": "public, max-age=3600"}
    if media_type == "image/svg+xml":
        # An SVG is a document that can carry script; served from this origin it
        # must not be able to run any.
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return Response(content=data, media_type=media_type, headers=headers)
