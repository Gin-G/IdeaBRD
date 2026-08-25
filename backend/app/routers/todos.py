from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import can_edit, idea_member_ids, resolve_idea
from app.auth import get_current_user
from app.db import get_session
from app.dualwrite import after_idea_change
from app.github import GitHubError
from app.gitsync import (
    import_issues,
    sync_issue_create,
    sync_issue_update,
    sync_push,
)
from app.models import Todo, User
from app.realtime import notify_idea
from app.schemas import ImportIssuesOut, TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/api", tags=["todos"])


async def _push_to_git(
    idea_id: int, user: User, session: AsyncSession, message: str
) -> None:
    """Best-effort commit of the idea's IDEA.md after a todo change.

    fresh: sessions here don't expire on commit, so an idea whose to-dos were
    loaded earlier in the request would otherwise be rendered from the list it
    had *before* this change — the push would commit the previous state.
    """
    idea, _role = await resolve_idea(
        session, idea_id, user, with_todos=True, fresh=True
    )
    if idea is not None and idea.github_repo:
        await sync_push(session, idea, user, message)
        await session.commit()


async def _after_push(session: AsyncSession, todo: Todo) -> Todo:
    """Re-read a to-do the push may have rewritten.

    A push that met a changed file merges it (see app.ideamerge) and writes the
    merged version back, so the row this request just wrote is not necessarily
    the row that ended up in the repo. Returning the stale one would show an
    edit that isn't there until the next load.
    """
    return await session.get(Todo, todo.id) or todo


async def _mirror_to_issue(
    idea_id: int, todo: Todo, user: User, session: AsyncSession
) -> None:
    """Best-effort mirror of a promoted to-do's text and state onto its issue.

    Failures are swallowed rather than failing the edit: the board is then ahead
    of GitHub, and the next pull resolves it the other way, since the issue wins.
    """
    if todo.github_issue_number is None:
        return
    idea, _role = await resolve_idea(session, idea_id, user)
    if idea is not None:
        await sync_issue_update(session, idea, todo, user)


async def _idea_for_todo(todo_id: int, session: AsyncSession) -> int | None:
    return await session.scalar(select(Todo.idea_id).where(Todo.id == todo_id))


async def _require_member(
    idea_id: int, user: User, session: AsyncSession, *, edit: bool
) -> None:
    idea, role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if edit and not can_edit(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access")


@router.get("/ideas/{idea_id}/todos", response_model=list[TodoOut])
async def list_todos(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_member(idea_id, user, session, edit=False)
    result = await session.execute(
        select(Todo).where(Todo.idea_id == idea_id).order_by(Todo.position, Todo.id)
    )
    return list(result.scalars().all())


@router.post(
    "/ideas/{idea_id}/todos",
    response_model=TodoOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_todo(
    idea_id: int,
    payload: TodoCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_member(idea_id, user, session, edit=True)
    max_pos = await session.scalar(
        select(func.coalesce(func.max(Todo.position), -1)).where(
            Todo.idea_id == idea_id
        )
    )
    todo = Todo(idea_id=idea_id, text=payload.text, position=max_pos + 1)
    session.add(todo)
    await session.commit()
    await session.refresh(todo)
    await notify_idea(session, idea_id, "updated")
    await after_idea_change(session, await idea_member_ids(session, idea_id))
    await _push_to_git(idea_id, user, session, f"Add todo: {payload.text[:50]}")
    return await _after_push(session, todo)


@router.patch("/todos/{todo_id}", response_model=TodoOut)
async def update_todo(
    todo_id: int,
    payload: TodoUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea_id = await _idea_for_todo(todo_id, session)
    if idea_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    await _require_member(idea_id, user, session, edit=True)
    todo = await session.get(Todo, todo_id)
    fields = payload.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(todo, field, value)
    await session.commit()
    await session.refresh(todo)
    # Reordering doesn't touch the issue; only what the issue itself carries does.
    if "done" in fields or "text" in fields:
        await _mirror_to_issue(idea_id, todo, user, session)
    await notify_idea(session, idea_id, "updated")
    await after_idea_change(session, await idea_member_ids(session, idea_id))
    await _push_to_git(idea_id, user, session, f"Update todo: {todo.text[:50]}")
    return await _after_push(session, todo)


@router.post("/todos/{todo_id}/issue", response_model=TodoOut)
async def promote_todo_to_issue(
    todo_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Open a GitHub issue for this to-do and bind the two together.

    The click *is* the opt-in, so unlike IDEA.md there's no separate tracking
    gate: nothing reaches the repo until someone asks for it here. Failures are
    surfaced rather than swallowed — a background sync can retry later, an
    explicit action that silently did nothing cannot.
    """
    idea_id = await _idea_for_todo(todo_id, session)
    if idea_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    idea, role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if not can_edit(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access")
    if not idea.github_repo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idea has no linked GitHub repo",
        )

    todo = await session.get(Todo, todo_id)
    if todo.github_issue_number is not None:
        return todo  # already promoted

    try:
        await sync_issue_create(session, idea, todo, user)
    except GitHubError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(todo)
    await notify_idea(session, idea_id, "updated")
    await after_idea_change(session, await idea_member_ids(session, idea_id))
    await _push_to_git(
        idea_id, user, session, f"Link todo to issue #{todo.github_issue_number}"
    )
    return await _after_push(session, todo)


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea_id = await _idea_for_todo(todo_id, session)
    if idea_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    await _require_member(idea_id, user, session, edit=True)
    todo = await session.get(Todo, todo_id)
    text = todo.text
    # A promoted to-do only unbinds here — closing someone's issue because a
    # tile was tidied up would be a surprising thing for a board to do.
    await session.delete(todo)
    await session.commit()
    await notify_idea(session, idea_id, "updated")
    await after_idea_change(session, await idea_member_ids(session, idea_id))
    await _push_to_git(idea_id, user, session, f"Remove todo: {text[:50]}")


@router.post("/ideas/{idea_id}/todos/import", response_model=ImportIssuesOut)
async def import_repo_issues(
    idea_id: int,
    state: str = "open",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Adopt the linked repo's issues as to-dos.

    Promotion has only ever run the other way: a to-do could become an issue,
    but a repo that already had issues arrived at an empty tile. Importing is
    the missing direction, and it is the same binding either way — an imported
    item is issue-backed, so the issue keeps owning its title and its state.

    ``state`` is "open" by default: a repo's closed issues are its history, and
    a board is for what is still in flight.
    """
    idea, role = await resolve_idea(session, idea_id, user, with_todos=True)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if not can_edit(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access")
    if not idea.github_repo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idea has no linked GitHub repo",
        )
    if state not in ("open", "closed", "all"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state must be open, closed or all",
        )
    try:
        added = await import_issues(session, idea, user, state=state)
    except GitHubError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await session.commit()
    if added:
        await notify_idea(session, idea_id, "updated")
        await after_idea_change(session, await idea_member_ids(session, idea_id))
        await _push_to_git(idea_id, user, session, f"Import {added} issue(s) as to-dos")
    todos = (
        (
            await session.execute(
                select(Todo)
                .where(Todo.idea_id == idea_id)
                .order_by(Todo.position, Todo.id)
            )
        )
        .scalars()
        .all()
    )
    return ImportIssuesOut(imported=added, todos=list(todos))
