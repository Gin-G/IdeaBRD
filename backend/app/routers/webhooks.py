"""GitHub webhooks: changes made on GitHub reaching the board on their own.

Everything else in this app pulls. Opening a tile fetches IDEA.md and the
issues behind its to-dos, which means a box ticked on GitHub sits there
unnoticed until somebody happens to look — and on a board of tiles, "happens to
look" can be weeks. A webhook closes that gap: GitHub tells us, we write it
down, and the change goes out over the WebSocket the app is already holding
open, so an issue closed on a phone reaches an open board in a second.

Only the two events that can change a tile are handled — ``issues`` and
``issue_comment`` for the to-dos behind it, ``push`` for IDEA.md and the logo —
and each one is applied to *every* idea that links the repo, since two people
may each have a tile pointing at it.

The endpoint is public by necessity, so the payload is authenticated the only
way GitHub offers: an HMAC of the raw body under a shared secret. Without a
secret configured the endpoint refuses to run at all rather than trusting
whatever arrives — an unauthenticated writer into other people's boards is not
a feature worth having by default.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.access import idea_member_ids
from app.config import settings
from app.db import get_session
from app.dualwrite import after_idea_change
from app.github import GitHubError, issue_from_payload
from app.gitsync import apply_issue, sync_pull
from app.models import Idea, Todo, User
from app.realtime import notify_idea
from app.repo_ref import InvalidRepoRef, normalize_repo
from app.schemas import WebhookResult

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

SIGNATURE_HEADER = "X-Hub-Signature-256"
# Actions that can change what a tile shows. Anything else (locked, pinned,
# milestoned) is acknowledged and dropped.
ISSUE_ACTIONS = frozenset(
    [
        "opened",
        "edited",
        "closed",
        "reopened",
        "deleted",
        "labeled",
        "unlabeled",
        "assigned",
        "unassigned",
    ]
)
COMMENT_ACTIONS = frozenset(["created", "deleted", "edited"])
# Files whose change means the tile itself moved. A push touching neither is
# ordinary development and costs nothing.
WATCHED_PREFIXES = ("IDEA.md", "idea_logo.")


def verify_signature(body: bytes, signature: str | None) -> None:
    """Reject anything not signed with the configured secret."""
    if not settings.github_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhooks are not configured on this server",
        )
    expected = (
        "sha256="
        + hmac.new(
            settings.github_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
    )
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature"
        )


def _repo_of(payload: dict) -> str | None:
    full_name = (payload.get("repository") or {}).get("full_name")
    if not full_name:
        return None
    try:
        return normalize_repo(full_name)
    except InvalidRepoRef:
        return None


async def _ideas_for(session: AsyncSession, repo: str) -> list[Idea]:
    """Every idea linking this repo — one webhook can change several boards.

    To-dos come along eagerly: a push handler renders the idea, and a lazy
    load of the collection from inside async code has nowhere to run.
    """
    return list(
        (
            await session.execute(
                select(Idea)
                .where(Idea.github_repo == repo)
                .options(selectinload(Idea.todos))
            )
        )
        .scalars()
        .all()
    )


async def _handle_issue(session: AsyncSession, repo: str, payload: dict) -> list[int]:
    """Apply an issue event to every to-do bound to that issue. Returns idea ids."""
    data = payload.get("issue") or {}
    if "number" not in data:
        return []
    issue = issue_from_payload(data)
    deleted = payload.get("action") == "deleted"
    touched: list[int] = []
    for idea in await _ideas_for(session, repo):
        todos = (
            (
                await session.execute(
                    select(Todo).where(
                        Todo.idea_id == idea.id,
                        Todo.github_issue_number == issue.number,
                    )
                )
            )
            .scalars()
            .all()
        )
        for todo in todos:
            if deleted:
                # The issue is gone, so nothing owns this item's text and state
                # any more; it survives as the plain to-do it started as rather
                # than vanishing along with the issue.
                todo.github_issue_number = None
                todo.github_issue_url = None
                todo.github_issue_labels = None
                todo.github_issue_assignee = None
                todo.github_issue_comments = None
            else:
                apply_issue(todo, issue, repo)
            if idea.id not in touched:
                touched.append(idea.id)
    return touched


def _touches_tile(payload: dict) -> bool:
    for commit in payload.get("commits") or ():
        for path in (
            *(commit.get("added") or ()),
            *(commit.get("modified") or ()),
            *(commit.get("removed") or ()),
        ):
            if path.startswith(WATCHED_PREFIXES):
                return True
    return False


async def _handle_push(session: AsyncSession, repo: str, payload: dict) -> list[int]:
    """Pull IDEA.md and the logo for ideas whose repo just changed.

    Only for a push that actually touched them, and only on the repo's default
    branch: a tile follows the branch it is read from, and adopting a feature
    branch's IDEA.md would make the board show work that isn't merged.
    """
    if not _touches_tile(payload):
        return []
    default = (payload.get("repository") or {}).get("default_branch") or "main"
    if payload.get("ref") not in (None, f"refs/heads/{default}"):
        return []
    touched: list[int] = []
    for idea in await _ideas_for(session, repo):
        owner = await session.get(User, idea.user_id)
        if owner is None:
            continue
        try:
            # The owner stands in for the acting user: a push has no session
            # behind it, and the owner's token is the one the tile syncs with.
            state = await sync_pull(session, idea, owner)
        except GitHubError:
            continue
        if state.changed:
            touched.append(idea.id)
    return touched


@router.post("/github", response_model=WebhookResult)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Receive a GitHub webhook and push what it changed to open boards."""
    body = await request.body()
    verify_signature(body, x_hub_signature_256)
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Body is not JSON"
        ) from exc

    if x_github_event == "ping":
        return WebhookResult(event="ping", handled=True)

    repo = _repo_of(payload)
    if repo is None:
        return WebhookResult(event=x_github_event)

    action = payload.get("action")
    ideas: list[int] = []
    if x_github_event == "issues" and action in ISSUE_ACTIONS:
        ideas = await _handle_issue(session, repo, payload)
    elif x_github_event == "issue_comment" and action in COMMENT_ACTIONS:
        ideas = await _handle_issue(session, repo, payload)
    elif x_github_event == "push":
        ideas = await _handle_push(session, repo, payload)
    else:
        return WebhookResult(event=x_github_event)

    await session.commit()
    for idea_id in ideas:
        await notify_idea(session, idea_id, "updated")
        # A change that arrived from GitHub still leaves the board repo behind,
        # so it is dual-written like any other.
        await after_idea_change(session, await idea_member_ids(session, idea_id))
    return WebhookResult(event=x_github_event, handled=True, ideas=len(ideas))
