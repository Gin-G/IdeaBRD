from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_session
from app.models import Idea, Todo, User
from app.schemas import TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/api", tags=["todos"])


async def _assert_owns_idea(
    idea_id: int, user: User, session: AsyncSession
) -> None:
    owner_id = await session.scalar(select(Idea.user_id).where(Idea.id == idea_id))
    if owner_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")


async def _get_owned_todo(
    todo_id: int, user: User, session: AsyncSession
) -> Todo:
    stmt = (
        select(Todo)
        .join(Idea, Todo.idea_id == Idea.id)
        .where(Todo.id == todo_id, Idea.user_id == user.id)
    )
    todo = (await session.execute(stmt)).scalar_one_or_none()
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return todo


@router.get("/ideas/{idea_id}/todos", response_model=list[TodoOut])
async def list_todos(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _assert_owns_idea(idea_id, user, session)
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
    await _assert_owns_idea(idea_id, user, session)
    max_pos = await session.scalar(
        select(func.coalesce(func.max(Todo.position), -1)).where(
            Todo.idea_id == idea_id
        )
    )
    todo = Todo(idea_id=idea_id, text=payload.text, position=max_pos + 1)
    session.add(todo)
    await session.commit()
    await session.refresh(todo)
    return todo


@router.patch("/todos/{todo_id}", response_model=TodoOut)
async def update_todo(
    todo_id: int,
    payload: TodoUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    todo = await _get_owned_todo(todo_id, user, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(todo, field, value)
    await session.commit()
    await session.refresh(todo)
    return todo


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    todo = await _get_owned_todo(todo_id, user, session)
    await session.delete(todo)
    await session.commit()
