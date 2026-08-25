"""Two-way sync between an idea and its linked GitHub repo.

Two files are tracked, both at the repo root: IDEA.md (title, notes, status,
to-dos) and the tile logo, `idea_logo.<ext>`. Git is the source of truth:
viewing an idea pulls both and overwrites the database copy when they changed;
edits made in the app are committed back through the Contents API. If the repo
has no IDEA.md yet, nothing is written until the user explicitly opts in
(sync_init) — the app never commits a new file to someone's repo unprompted,
and the same gate covers logo commits. Deleting IDEA.md in git puts the idea
back in that untracked state, so removing the file is a real opt-out rather
than something the next app edit undoes.

The logo pull is what makes a repo carry its own tile: link a repo that already
has an idea_logo.png and the tile picks the image up without anyone uploading
it, whoever links it.

A to-do can also be promoted to a **GitHub issue**, after which the issue —
not IDEA.md — owns its text and open/closed state, and the file just carries
the reference ("- [ ] Build MVP (#12)"). That gives the item a stable identity:
plain to-dos are matched between file and board by exact text, so rewording one
replaces it, where a promoted one can be reworded freely.

Sync is best-effort — the helpers return an error message instead of raising,
so a GitHub outage or missing token never blocks the app itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.github import (
    GitHubError,
    Issue,
    create_issue,
    delete_file,
    get_blob,
    get_file,
    list_dir,
    list_issues,
    put_file,
    update_issue,
)
from app.ideafile import (
    ParsedIdeaFile,
    ParsedTodo,
    parse_idea_file,
    render_idea_file,
)
from app.ideamerge import merge_idea_files
from app.logos import (
    LOGO_NAMES,
    MAX_LOGO_BYTES,
    content_type_for_path,
    logo_path_for,
)
from app.models import Idea, IdeaLogo, Identity, Todo, User

IDEA_FILE = "IDEA.md"
COMMIT_AUTHOR_NOTE = "via IdeaBRD"


@dataclass
class SyncStatus:
    changed: bool = False  # pull rewrote the idea (content or tracking state)
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
        todos=[ParsedTodo(t.text, t.done, t.github_issue_number) for t in todos],
    )


def _issue_url(repo: str, number: int) -> str:
    return f"https://github.com/{repo}/issues/{number}"


async def _apply_todos(
    session: AsyncSession, idea: Idea, parsed: list[ParsedTodo]
) -> bool:
    """Make the idea's todos match the file, reusing rows to keep ids.

    An item carrying an issue number matches the row already bound to that
    issue, whatever either one says: the number is stable where the text is
    not, so reworded issue-backed items are edited in place instead of being
    replaced. Everything else still matches on exact text.
    """
    remaining = sorted(idea.todos, key=lambda t: (t.position, t.id))
    changed = False
    for pos, item in enumerate(parsed):
        text = item.text[:500]
        if item.issue is not None:
            match = next(
                (t for t in remaining if t.github_issue_number == item.issue), None
            )
            # Not bound yet: an issue reference added by hand adopts the to-do
            # whose text it matches rather than duplicating it.
            if match is None:
                match = next(
                    (
                        t
                        for t in remaining
                        if t.github_issue_number is None and t.text == text
                    ),
                    None,
                )
        else:
            match = next(
                (
                    t
                    for t in remaining
                    if t.github_issue_number is None and t.text == text
                ),
                None,
            )
        if match:
            remaining.remove(match)
            url = _issue_url(idea.github_repo, item.issue) if item.issue else None
            if (
                match.done != item.done
                or match.position != pos
                or match.text != text
                or match.github_issue_number != item.issue
            ):
                if match.github_issue_number != item.issue and item.issue is None:
                    # The reference was taken out of the file by hand: the item
                    # is an ordinary to-do again, and mirrored issue context it
                    # kept would be about an issue it no longer tracks.
                    match.github_issue_labels = None
                    match.github_issue_assignee = None
                    match.github_issue_comments = None
                match.text = text
                match.done = item.done
                match.position = pos
                match.github_issue_number = item.issue
                match.github_issue_url = url
                changed = True
        else:
            session.add(
                Todo(
                    idea_id=idea.id,
                    text=text,
                    done=item.done,
                    position=pos,
                    github_issue_number=item.issue,
                    github_issue_url=(
                        _issue_url(idea.github_repo, item.issue) if item.issue else None
                    ),
                )
            )
            changed = True
    for leftover in remaining:
        # AsyncSession.delete() is a coroutine — without the await the row survives
        # and the file's removed to-dos come back as duplicates on the next pull.
        await session.delete(leftover)
        changed = True
    return changed


async def _apply_parsed(
    session: AsyncSession, idea: Idea, parsed: ParsedIdeaFile
) -> bool:
    """Overwrite the idea with a parsed file's content (git wins).

    Split from ``_apply_file`` because a merged push has a parse in hand
    already and has to write it back: the merge result is what landed in the
    repo, so the board has to end up holding the same thing.
    """
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
    return await _apply_todos(session, idea, parsed.todos) or changed


async def _apply_file(session: AsyncSession, idea: Idea, text: str, sha: str) -> bool:
    """Overwrite the idea with the file's content and record the sync."""
    changed = await _apply_parsed(session, idea, parse_idea_file(text))
    idea.github_file_sha = sha
    idea.git_synced_at = datetime.now(timezone.utc)
    return changed


async def _base_text(idea: Idea, token: str | None) -> str | None:
    """The IDEA.md we last synced, fetched by the blob sha we recorded.

    This is what makes a push a three-way merge rather than a guess: without
    the common ancestor, an item missing from the repo is indistinguishable
    from one somebody just added here. A sha we can no longer fetch degrades
    the merge to a union rather than failing the push.
    """
    if not idea.github_file_sha:
        return None
    try:
        return (
            await get_blob(idea.github_repo, idea.github_file_sha, token=token)
        ).decode("utf-8")
    except (GitHubError, UnicodeDecodeError):
        return None


async def _push(session: AsyncSession, idea: Idea, token: str | None, message: str) -> None:
    """Commit the idea's current state to IDEA.md, merging if the file moved.

    A 409 means the file changed on GitHub since we last read it. Overwriting
    it is what a sha check exists to prevent, so instead the two versions are
    merged by meaning (see app.ideamerge) and the merged file is both pushed
    and written back to the idea — the repo and the board then hold the same
    thing, which is the only outcome that leaves nothing to discover later.
    """
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
        if found is None:
            # Deleted on GitHub rather than edited: recreate it as it stands,
            # since that is what the caller asked to commit.
            sha = await put_file(
                idea.github_repo, IDEA_FILE, content, message, sha=None, token=token
            )
        else:
            theirs, their_sha = found
            merged, parsed = merge_idea_files(
                await _base_text(idea, token), content, theirs
            )
            sha = await put_file(
                idea.github_repo,
                IDEA_FILE,
                merged,
                f"{message} [merged]",
                sha=their_sha,
                token=token,
            )
            await _apply_parsed(session, idea, parsed)
    idea.github_file_sha = sha
    idea.git_synced_at = datetime.now(timezone.utc)


def _repo_logo(entries: dict[str, tuple[str, int]]) -> tuple[str, str, int] | None:
    """Pick the repo's tile logo from a root listing: (path, blob sha, size)."""
    for name in LOGO_NAMES:
        entry = entries.get(name)
        if entry is not None:
            return name, entry[0], entry[1]
    return None


async def _clear_logo(session: AsyncSession, idea: Idea) -> None:
    stored = await session.get(IdeaLogo, idea.id)
    if stored is not None:
        await session.delete(stored)
    idea.logo_url = None
    idea.github_logo_path = None
    idea.github_logo_sha = None


async def _pull_logo(session: AsyncSession, idea: Idea, token: str | None) -> bool:
    """Adopt the repo's idea_logo.<ext> as the tile image (git wins).

    Returns True when the tile changed. A logo that was tracked in git and has
    since been deleted there is dropped here too; a logo that was only ever
    uploaded in the app (no sha recorded) is left alone, since git never had it.
    """
    entries = await list_dir(idea.github_repo, token=token)
    found = _repo_logo(entries)
    if found is None:
        if idea.github_logo_sha is None:
            return False
        await _clear_logo(session, idea)
        return True

    path, sha, size = found
    if sha == idea.github_logo_sha and path == idea.github_logo_path:
        return False
    content_type = content_type_for_path(path)
    if content_type is None or size > MAX_LOGO_BYTES:
        # Too big to serve back from the database; leave the tile as it is.
        return False

    data = await get_blob(idea.github_repo, sha, token=token)
    stored = await session.get(IdeaLogo, idea.id)
    if stored is None:
        session.add(IdeaLogo(idea_id=idea.id, content_type=content_type, data=data))
    else:
        stored.content_type = content_type
        stored.data = data
    # Version on the blob sha: it changes exactly when the image content does.
    idea.logo_url = f"/api/ideas/{idea.id}/logo?v={sha[:16]}"
    idea.github_logo_path = path
    idea.github_logo_sha = sha
    return True


async def _pull_issues(session: AsyncSession, idea: Idea, token: str | None) -> bool:
    """Apply live issue titles and open/closed state to issue-backed to-dos.

    Runs after the file has been applied and overrides it: for an item that was
    promoted to an issue, the issue is the source of truth, not the checkbox
    someone left in IDEA.md.

    Nothing is committed back from here. The file catches up on the next
    app-side edit, which keeps the rule that IdeaBRD only writes to a repo in
    response to a user action — opening a tile is not one.
    """
    # Rows added while applying the file aren't in idea.todos yet.
    await session.flush()
    linked = (
        (
            await session.execute(
                select(Todo).where(
                    Todo.idea_id == idea.id, Todo.github_issue_number.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not linked:
        return False

    issues = await list_issues(idea.github_repo, token=token)
    changed = False
    for todo in linked:
        issue = issues.get(todo.github_issue_number)
        if issue is None:
            continue  # beyond the pages pulled, or deleted; leave it as it is
        if apply_issue(todo, issue, idea.github_repo):
            changed = True
    return changed


def apply_issue(todo: Todo, issue: Issue, repo: str) -> bool:
    """Copy an issue onto the to-do it backs. True when anything moved.

    Shared with the webhook receiver, which is handed one issue rather than a
    listing: a to-do has to end up in the same state whether the news arrived
    because someone opened the tile or because GitHub pushed it.
    """
    labels = list(issue.labels)
    fields = {
        "done": issue.state == "closed",
        "text": (issue.title or todo.text)[:500],
        "github_issue_url": issue.html_url or _issue_url(repo, issue.number),
        "github_issue_labels": labels,
        "github_issue_assignee": issue.assignee,
        "github_issue_comments": issue.comments,
    }
    changed = False
    for name, value in fields.items():
        if getattr(todo, name) != value:
            setattr(todo, name, value)
            changed = True
    return changed


async def import_issues(
    session: AsyncSession, idea: Idea, user: User, *, state: str = "open"
) -> int:
    """Adopt the repo's issues as to-dos, returning how many were added.

    The other direction has existed since to-dos could be promoted, which left
    a repo with a hundred issues and a tile with none — the board could only
    ever push work into GitHub, never pick up work that started there. An
    issue already backing a to-do is skipped, so importing twice is a no-op
    rather than a pile of duplicates.

    Raises GitHubError: importing is a click, and a click that quietly did
    nothing is worse than an error message.
    """
    if not idea.github_repo:
        return 0
    token = await resolve_token(session, idea, user)
    issues = await list_issues(idea.github_repo, state=state, token=token)
    known = set(
        (
            await session.execute(
                select(Todo.github_issue_number).where(
                    Todo.idea_id == idea.id, Todo.github_issue_number.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    position = await session.scalar(
        select(func.coalesce(func.max(Todo.position), -1)).where(
            Todo.idea_id == idea.id
        )
    )
    added = 0
    for number in sorted(issues):
        if number in known:
            continue
        issue = issues[number]
        position += 1
        todo = Todo(idea_id=idea.id, text="", position=position)
        apply_issue(todo, issue, idea.github_repo)
        todo.github_issue_number = number
        session.add(todo)
        added += 1
    return added


async def sync_issue_create(
    session: AsyncSession, idea: Idea, todo: Todo, user: User
) -> None:
    """Open an issue for a to-do and bind the two together.

    Raises GitHubError — promoting is an explicit click, so a failure is
    reported rather than swallowed the way background syncs are.
    """
    token = await resolve_token(session, idea, user)
    issue = await create_issue(
        idea.github_repo,
        todo.text,
        f"Tracked on the IdeaBRD board under **{idea.title}**.",
        token=token,
    )
    apply_issue(todo, issue, idea.github_repo)
    todo.github_issue_number = issue.number


async def sync_issue_update(
    session: AsyncSession, idea: Idea, todo: Todo, user: User
) -> str | None:
    """Mirror a to-do's text and done state onto its issue. Best-effort.

    A failure here leaves the board ahead of GitHub, which the next pull
    corrects in GitHub's favour — the issue always wins in the end.
    """
    if todo.github_issue_number is None or not idea.github_repo:
        return None
    try:
        token = await resolve_token(session, idea, user)
        await update_issue(
            idea.github_repo,
            todo.github_issue_number,
            title=todo.text,
            state="closed" if todo.done else "open",
            token=token,
        )
        return None
    except GitHubError as exc:
        return str(exc)


async def sync_pull(session: AsyncSession, idea: Idea, user: User) -> SyncStatus:
    """Best-effort pull of IDEA.md and the tile logo into the idea (git wins).

    A missing IDEA.md is reported, never created — creating it is an explicit
    user choice (sync_init), whether the repo never had one or the file was
    deleted there. The logo is pulled either way: adopting artwork the repo
    already carries doesn't write anything back.
    """
    if not idea.github_repo:
        return SyncStatus()
    state = SyncStatus()
    try:
        token = await resolve_token(session, idea, user)
        found = await get_file(idea.github_repo, IDEA_FILE, token=token)
        if found is None:
            state.file_missing = True
            if idea.github_file_sha is not None:
                # Tracked until now, deleted in git since: drop the tracking
                # state, the same way a deleted logo is dropped. Keeping the
                # stale sha would leave the page claiming the file is there and
                # would let the next app edit push it back — recreating a file
                # the user removed, without ever asking.
                idea.github_file_sha = None
                idea.git_synced_at = None
                state.changed = True
        else:
            text, sha = found
            if sha == idea.github_file_sha:
                idea.git_synced_at = datetime.now(timezone.utc)
            else:
                state.changed = await _apply_file(session, idea, text, sha)
    except GitHubError as exc:
        return SyncStatus(error=str(exc))
    try:
        if await _pull_issues(session, idea, token):
            state.changed = True
    except GitHubError as exc:
        state.error = str(exc)
    try:
        if await _pull_logo(session, idea, token):
            state.changed = True
    except GitHubError as exc:
        state.error = str(exc)
    return state


async def sync_init(session: AsyncSession, idea: Idea, user: User) -> str | None:
    """Create IDEA.md from the idea's current state — the user opted in to
    tracking this idea in the repo. Returns an error message, or None.

    An image uploaded before the opt-in goes up in the same breath, so the repo
    ends up with everything the tile is made of rather than half of it.
    """
    if not idea.github_repo:
        return None
    try:
        token = await resolve_token(session, idea, user)
        await _push(
            session, idea, token, f"Track idea in {IDEA_FILE} ({COMMIT_AUTHOR_NOTE})"
        )
        stored = await session.get(IdeaLogo, idea.id)
        if stored is not None and idea.github_logo_sha is None:
            await _push_logo(idea, stored.data, stored.content_type, token)
        return None
    except GitHubError as exc:
        return str(exc)


async def _remote_logo_sha(idea: Idea, path: str, token: str | None) -> str | None:
    """Current blob sha of a repo logo path, for recovering from a stale sha."""
    entries = await list_dir(idea.github_repo, token=token)
    entry = entries.get(path)
    return entry[0] if entry else None


async def _push_logo(
    idea: Idea, data: bytes, content_type: str, token: str | None
) -> None:
    """Commit image bytes as idea_logo.<ext>, retrying once on a stale sha.

    Replacing a logo with a different format also removes the old file, so the
    repo keeps exactly one.
    """
    path = logo_path_for(content_type)
    previous = idea.github_logo_path
    message = f"Update idea logo ({COMMIT_AUTHOR_NOTE})"
    sha = idea.github_logo_sha if previous == path else None
    try:
        new_sha = await put_file(
            idea.github_repo, path, data, message, sha=sha, token=token
        )
    except GitHubError as exc:
        if exc.status_code != 409:
            raise
        new_sha = await put_file(
            idea.github_repo,
            path,
            data,
            message,
            sha=await _remote_logo_sha(idea, path, token),
            token=token,
        )
    idea.github_logo_path = path
    idea.github_logo_sha = new_sha
    if previous and previous != path:
        old_sha = await _remote_logo_sha(idea, previous, token)
        if old_sha:
            await delete_file(
                idea.github_repo,
                previous,
                f"Remove replaced idea logo ({COMMIT_AUTHOR_NOTE})",
                sha=old_sha,
                token=token,
            )


async def sync_logo_push(
    session: AsyncSession, idea: Idea, user: User, data: bytes, content_type: str
) -> str | None:
    """Commit an uploaded image to the repo as idea_logo.<ext>.

    Gated on tracking like every other push, so uploading an image never creates
    files in a repo the user hasn't opted into — sync_init picks it up later.
    """
    if not idea.github_repo or idea.github_file_sha is None:
        return None
    try:
        token = await resolve_token(session, idea, user)
        await _push_logo(idea, data, content_type, token)
        return None
    except GitHubError as exc:
        return str(exc)


async def sync_logo_delete(session: AsyncSession, idea: Idea, user: User) -> str | None:
    """Commit the removal of the repo's logo file.

    Without this the next pull would re-adopt the image from git and silently
    undo the removal, since git wins.
    """
    if not idea.github_repo or not idea.github_logo_path:
        return None
    path = idea.github_logo_path
    message = f"Remove idea logo ({COMMIT_AUTHOR_NOTE})"
    try:
        token = await resolve_token(session, idea, user)
        try:
            await delete_file(
                idea.github_repo, path, message, sha=idea.github_logo_sha, token=token
            )
        except GitHubError as exc:
            if exc.status_code != 409:
                raise
            current = await _remote_logo_sha(idea, path, token)
            if current:
                await delete_file(
                    idea.github_repo, path, message, sha=current, token=token
                )
        idea.github_logo_path = None
        idea.github_logo_sha = None
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
