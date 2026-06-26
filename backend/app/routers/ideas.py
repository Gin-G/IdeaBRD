from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.db import get_session
from app.models import Idea, User
from app.schemas import (
    IdeaCreate,
    IdeaOut,
    IdeaSummary,
    IdeaUpdate,
    ReorderItem,
)

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


async def _get_owned_idea(
    idea_id: int, user: User, session: AsyncSession, *, with_todos: bool = False
) -> Idea:
    stmt = select(Idea).where(Idea.id == idea_id, Idea.user_id == user.id)
    if with_todos:
        stmt = stmt.options(selectinload(Idea.todos))
    idea = (await session.execute(stmt)).scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    return idea


@router.get("", response_model=list[IdeaSummary])
async def list_ideas(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Idea)
        .where(Idea.user_id == user.id)
        .order_by(Idea.position, Idea.id)
    )
    return list(result.scalars().all())


@router.post("", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
async def create_idea(
    payload: IdeaCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    max_pos = await session.scalar(
        select(func.coalesce(func.max(Idea.position), -1)).where(
            Idea.user_id == user.id
        )
    )
    idea = Idea(user_id=user.id, position=max_pos + 1, **payload.model_dump())
    session.add(idea)
    await session.commit()
    # Re-select so server-side defaults (timestamps) and the todos relationship load.
    return await _get_owned_idea(idea.id, user, session, with_todos=True)


@router.patch("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_ideas(
    items: list[ReorderItem],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update grid positions for a batch of the user's ideas."""
    owned = {
        i
        for i in (
            await session.execute(
                select(Idea.id).where(Idea.user_id == user.id)
            )
        ).scalars()
    }
    for item in items:
        if item.id in owned:
            await session.execute(
                Idea.__table__.update()
                .where(Idea.id == item.id)
                .values(position=item.position)
            )
    await session.commit()


@router.get("/{idea_id}", response_model=IdeaOut)
async def get_idea(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _get_owned_idea(idea_id, user, session, with_todos=True)


@router.patch("/{idea_id}", response_model=IdeaOut)
async def update_idea(
    idea_id: int,
    payload: IdeaUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea = await _get_owned_idea(idea_id, user, session, with_todos=True)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(idea, field, value)
    await session.commit()
    return await _get_owned_idea(idea_id, user, session, with_todos=True)


@router.delete("/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_idea(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea = await _get_owned_idea(idea_id, user, session)
    await session.delete(idea)
    await session.commit()
