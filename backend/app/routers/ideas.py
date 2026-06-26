from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    can_edit,
    idea_member_ids,
    resolve_idea,
    user_board_max_position,
)
from app.auth import get_current_user
from app.db import get_session
from app.models import Idea, IdeaCollaborator, IdeaInvitation, User
from app.realtime import notify_idea
from app.schemas import (
    IdeaCreate,
    IdeaOut,
    IdeaSummary,
    IdeaUpdate,
    OwnerInfo,
    ReorderItem,
)

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


def _idea_out(idea: Idea, role: str, owner: User | None) -> IdeaOut:
    out = IdeaOut.model_validate(idea)
    out.role = role
    if owner is not None and owner.id != idea.user_id:
        owner = None  # safety
    if role != "owner" and owner is not None:
        out.owner = OwnerInfo(
            name=owner.name, email=owner.email, avatar_url=owner.avatar_url
        )
    return out


@router.get("", response_model=list[IdeaSummary])
async def list_ideas(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """The user's board: ideas they own plus ideas shared with them."""
    owned = (
        (await session.execute(select(Idea).where(Idea.user_id == user.id)))
        .scalars()
        .all()
    )
    owned_ids = [i.id for i in owned]
    shared_owned: set[int] = set()
    if owned_ids:
        c = (
            await session.execute(
                select(IdeaCollaborator.idea_id).where(
                    IdeaCollaborator.idea_id.in_(owned_ids)
                )
            )
        ).scalars().all()
        inv = (
            await session.execute(
                select(IdeaInvitation.idea_id).where(
                    IdeaInvitation.idea_id.in_(owned_ids)
                )
            )
        ).scalars().all()
        shared_owned = set(c) | set(inv)

    summaries = [
        IdeaSummary.model_validate(
            {
                **i.__dict__,
                "role": "owner",
                "shared": False,
                "has_collaborators": i.id in shared_owned,
            }
        )
        for i in owned
    ]

    rows = (
        await session.execute(
            select(Idea, IdeaCollaborator.role, IdeaCollaborator.position, User)
            .join(IdeaCollaborator, IdeaCollaborator.idea_id == Idea.id)
            .join(User, User.id == Idea.user_id)
            .where(IdeaCollaborator.user_id == user.id)
        )
    ).all()
    for idea, role, pos, owner in rows:
        summaries.append(
            IdeaSummary(
                id=idea.id,
                title=idea.title,
                status=idea.status,
                progress=idea.progress,
                color=idea.color,
                logo_url=idea.logo_url,
                github_repo=idea.github_repo,
                position=pos,
                role=role,
                shared=True,
                owner=OwnerInfo(
                    name=owner.name, email=owner.email, avatar_url=owner.avatar_url
                ),
            )
        )

    summaries.sort(key=lambda s: (s.position, s.id))
    return summaries


@router.post("", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
async def create_idea(
    payload: IdeaCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    pos = await user_board_max_position(session, user.id)
    idea = Idea(user_id=user.id, position=pos + 1, **payload.model_dump())
    session.add(idea)
    await session.commit()
    idea, role = await resolve_idea(session, idea.id, user, with_todos=True)
    return _idea_out(idea, role, None)


@router.patch("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_ideas(
    items: list[ReorderItem],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update grid positions on the user's own board (owned and shared ideas)."""
    owned = {
        i
        for i in (
            await session.execute(select(Idea.id).where(Idea.user_id == user.id))
        ).scalars()
    }
    shared = {
        i
        for i in (
            await session.execute(
                select(IdeaCollaborator.idea_id).where(
                    IdeaCollaborator.user_id == user.id
                )
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
        elif item.id in shared:
            await session.execute(
                IdeaCollaborator.__table__.update()
                .where(
                    IdeaCollaborator.idea_id == item.id,
                    IdeaCollaborator.user_id == user.id,
                )
                .values(position=item.position)
            )
    await session.commit()


@router.get("/{idea_id}", response_model=IdeaOut)
async def get_idea(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea, role = await resolve_idea(session, idea_id, user, with_todos=True)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    owner = None if role == "owner" else await session.get(User, idea.user_id)
    return _idea_out(idea, role, owner)


@router.patch("/{idea_id}", response_model=IdeaOut)
async def update_idea(
    idea_id: int,
    payload: IdeaUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea, role = await resolve_idea(session, idea_id, user, with_todos=True)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if not can_edit(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access")
    data = payload.model_dump(exclude_unset=True)
    # position is per-user board ordering; only via /reorder.
    data.pop("position", None)
    for field, value in data.items():
        setattr(idea, field, value)
    await session.commit()
    idea, role = await resolve_idea(session, idea_id, user, with_todos=True)
    await notify_idea(session, idea_id, "updated")
    owner = None if role == "owner" else await session.get(User, idea.user_id)
    return _idea_out(idea, role, owner)


@router.delete("/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_idea(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea, role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can delete"
        )
    member_ids = await idea_member_ids(session, idea_id)
    await session.delete(idea)
    await session.commit()
    await notify_idea(session, idea_id, "deleted", member_ids=member_ids)
