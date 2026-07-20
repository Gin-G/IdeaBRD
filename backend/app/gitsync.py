"""Two-way sync between an idea and IDEA.md in its linked GitHub repo.

Git is the source of truth: viewing an idea pulls IDEA.md and overwrites the
database copy when the file changed; edits made in the app are committed back
through the Contents API. If the repo has no IDEA.md yet, nothing is written
until the user explicitly opts in (sync_init) — the app never commits a new
file to someone's repo unprompted.

Sync is best-effort — the helpers return an error message instead of raising,
so a GitHub outage or missing token never blocks the app itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.github import GitHubError, get_file, put_file
from app.ideafile import parse_idea_file, render_idea_file
from app.models import Idea, Identity, Todo, User

IDEA_FILE = "IDEA.md"
COMMIT_AUTHOR_NOTE = "via IdeaBRD"


@dataclass
class SyncStatus:
    changed: bool = False  # pull rewrote idea content
    file_missing: bool = False  # repo has no IDEA.md (tracking not started)
    error: str | None = None


async def resolve_token(
    session: AsyncSession, idea: Idea, user: User
) -> str | None:
    """Best GitHub token for this idea: owner's, then the acting user's.

    Falls back to None, in which case the server-wide token (if configured)
    is used by the GitHub client.
    """
    tokens = {
        row.user_id: row.github_token
        for row in (
            await session.execute(
                select(Identity.user_id, Identity.github_token).where(
                    Identity.user_id.in_({idea.user_id, user.id}),
                    Identity.provider == "github",
                    Identity.github_token.is_not(None),
                )
            )
        ).all()
    }
    return tokens.get(idea.user_id) or tokens.get(user.id)


def _render(idea: Idea) -> str:
    todos = sorted(idea.todos, key=lambda t: (t.position, t.id))
    return render_idea_file(
        title=idea.title,
        notes=idea.notes,
        status=idea.status,
        progress=idea.progress,
        todos=[(t.text, t.done) for t in todos],
    )


def _apply_todos(session: AsyncSession, idea: Idea, parsed: list[tuple[str, bool]]) -> bool:
    """Make the idea's todos match the file, reusing rows by text to keep ids."""
    remaining = sorted(idea.todos, key=lambda t: (t.position, t.id))
    changed = False
    for pos, (text, done) in enumerate(parsed):
        text = text[:500]
        match = next((t for t in remaining if t.text == text), None)
        if match:
            remaining.remove(match)
            if match.done != done or match.position != pos:
                match.done = done
                match.position = pos
                changed = True
        else:
            session.add(Todo(idea_id=idea.id, text=text, done=done, position=pos))
            changed = True
    for leftover in remaining:
        session.delete(leftover)
        changed = True
    return changed


def _apply_file(session: AsyncSession, idea: Idea, text: str, sha: str) -> bool:
    """Overwrite the idea with the file's content (git wins)."""
    parsed = parse_idea_file(text)
    changed = False
    if parsed.title and parsed.title[:255] != idea.title:
        idea.title = parsed.title[:255]
        changed = True
    if parsed.notes != idea.notes:
        idea.notes = parsed.notes
        changed = True
    if parsed.status is not None and parsed.status != idea.status:
        idea.status = parsed.status
        changed = True
    if parsed.progress is not None and parsed.progress != idea.progress:
        idea.progress = parsed.progress
        changed = True
    changed = _apply_todos(session, idea, parsed.todos) or changed
    idea.github_file_sha = sha
    idea.git_synced_at = datetime.now(timezone.utc)
    return changed


async def _push(session: AsyncSession, idea: Idea, token: str | None, message: str) -> None:
    """Commit the idea's current state to IDEA.md, retrying once on a stale sha."""
    content = _render(idea)
    try:
        sha = await put_file(
            idea.github_repo,
            IDEA_FILE,
            content,
            message,
            sha=idea.github_file_sha,
            token=token,
        )
    except GitHubError as exc:
        if exc.status_code != 409:
            raise
        found = await get_file(idea.github_repo, IDEA_FILE, token=token)
        sha = await put_file(
            idea.github_repo,
            IDEA_FILE,
            content,
            message,
            sha=found[1] if found else None,
            token=token,
        )
    idea.github_file_sha = sha
    idea.git_synced_at = datetime.now(timezone.utc)


async def sync_pull(session: AsyncSession, idea: Idea, user: User) -> SyncStatus:
    """Best-effort pull of IDEA.md into the idea (git wins).

    A missing file is reported, never created — creating it is an explicit
    user choice (sync_init).
    """
    if not idea.github_repo:
        return SyncStatus()
    try:
        token = await resolve_token(session, idea, user)
        found = await get_file(idea.github_repo, IDEA_FILE, token=token)
        if found is None:
            return SyncStatus(file_missing=True)
        text, sha = found
        if sha == idea.github_file_sha:
            idea.git_synced_at = datetime.now(timezone.utc)
            return SyncStatus()
        return SyncStatus(changed=_apply_file(session, idea, text, sha))
    except GitHubError as exc:
        return SyncStatus(error=str(exc))


async def sync_init(session: AsyncSession, idea: Idea, user: User) -> str | None:
    """Create IDEA.md from the idea's current state — the user opted in to
    tracking this idea in the repo. Returns an error message, or None."""
    if not idea.github_repo:
        return None
    try:
        token = await resolve_token(session, idea, user)
        await _push(
            session, idea, token, f"Track idea in {IDEA_FILE} ({COMMIT_AUTHOR_NOTE})"
        )
        return None
    except GitHubError as exc:
        return str(exc)


async def sync_push(
    session: AsyncSession, idea: Idea, user: User, message: str
) -> str | None:
    """Best-effort push. Returns an error message, or None on success.

    Skipped until tracking is established (IDEA.md pulled or seeded at least
    once) so app edits never create the file behind the user's back.
    """
    if not idea.github_repo or idea.github_file_sha is None:
        return None
    try:
        token = await resolve_token(session, idea, user)
        await _push(session, idea, token, f"{message} ({COMMIT_AUTHOR_NOTE})")
        return None
    except GitHubError as exc:
        return str(exc)
