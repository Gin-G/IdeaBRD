from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import can_edit, resolve_idea
from app.auth import get_current_user
from app.db import get_session
from app.gitsync import sync_push
from app.models import Idea, Todo, User
from app.realtime import notify_idea
from app.schemas import TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/api", tags=["todos"])


async def _push_to_git(
    idea_id: int, user: User, session: AsyncSession, message: str
) -> None:
    """Best-effort commit of the idea's IDEA.md after a todo change."""
    idea, _role = await resolve_idea(session, idea_id, user, with_todos=True)
    if idea is not None and idea.github_repo:
        await sync_push(session, idea, user, message)
        await session.commit()


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
    await _push_to_git(idea_id, user, session, f"Add todo: {payload.text[:50]}")
    return todo


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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(todo, field, value)
    await session.commit()
    await session.refresh(todo)
    await notify_idea(session, idea_id, "updated")
    await _push_to_git(idea_id, user, session, f"Update todo: {todo.text[:50]}")
    return todo


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
    await session.delete(todo)
    await session.commit()
    await notify_idea(session, idea_id, "updated")
    await _push_to_git(idea_id, user, session, f"Remove todo: {text[:50]}")
