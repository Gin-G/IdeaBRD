from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import resolve_idea, user_board_max_position
from app.auth import get_current_user
from app.db import get_session
from app.models import (
    ROLE_EDITOR,
    ROLE_VIEWER,
    IdeaCollaborator,
    IdeaInvitation,
    User,
)
from app.realtime import notify_board, notify_idea
from app.schemas import CollaboratorOut, InviteIn

router = APIRouter(prefix="/api/ideas", tags=["collaborators"])

VALID_ROLES = {ROLE_EDITOR, ROLE_VIEWER}


async def _require_owner(idea_id, user, session):
    idea, role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can manage sharing"
        )
    return idea


@router.get("/{idea_id}/collaborators", response_model=list[CollaboratorOut])
async def list_collaborators(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Owner + active collaborators + pending invites. Any member may view."""
    idea, role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")

    owner = await session.get(User, idea.user_id)
    out = [
        CollaboratorOut(
            status="active",
            role="owner",
            is_owner=True,
            user_id=owner.id,
            email=owner.email,
            name=owner.name,
            avatar_url=owner.avatar_url,
        )
    ]
    rows = (
        await session.execute(
            select(IdeaCollaborator, User)
            .join(User, User.id == IdeaCollaborator.user_id)
            .where(IdeaCollaborator.idea_id == idea_id)
            .order_by(IdeaCollaborator.created_at)
        )
    ).all()
    for collab, u in rows:
        out.append(
            CollaboratorOut(
                status="active",
                role=collab.role,
                user_id=u.id,
                email=u.email,
                name=u.name,
                avatar_url=u.avatar_url,
            )
        )
    invites = (
        await session.execute(
            select(IdeaInvitation)
            .where(IdeaInvitation.idea_id == idea_id)
            .order_by(IdeaInvitation.created_at)
        )
    ).scalars().all()
    for inv in invites:
        out.append(
            CollaboratorOut(
                status="pending",
                role=inv.role,
                email=inv.email,
                invite_id=inv.id,
            )
        )
    return out


@router.post(
    "/{idea_id}/collaborators",
    response_model=CollaboratorOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_collaborator(
    idea_id: int,
    payload: InviteIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    idea = await _require_owner(idea_id, user, session)
    role = payload.role if payload.role in VALID_ROLES else ROLE_EDITOR
    email = payload.email.strip().lower()

    owner = await session.get(User, idea.user_id)
    if owner.email and owner.email.lower() == email:
        raise HTTPException(status_code=400, detail="You already own this idea")

    target = (
        await session.execute(
            select(User).where(func.lower(User.email) == email)
        )
    ).scalar_one_or_none()

    if target is not None:
        existing = (
            await session.execute(
                select(IdeaCollaborator).where(
                    IdeaCollaborator.idea_id == idea_id,
                    IdeaCollaborator.user_id == target.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.role = role
        else:
            pos = await user_board_max_position(session, target.id)
            session.add(
                IdeaCollaborator(
                    idea_id=idea_id, user_id=target.id, role=role, position=pos + 1
                )
            )
        await session.commit()
        await notify_board([target.id])
        await notify_idea(session, idea_id, "updated")
        return CollaboratorOut(
            status="active",
            role=role,
            user_id=target.id,
            email=target.email,
            name=target.name,
            avatar_url=target.avatar_url,
        )

    # No account yet -> pending invite, claimed on first login.
    existing_inv = (
        await session.execute(
            select(IdeaInvitation).where(
                IdeaInvitation.idea_id == idea_id, IdeaInvitation.email == email
            )
        )
    ).scalar_one_or_none()
    if existing_inv is not None:
        existing_inv.role = role
        invite = existing_inv
    else:
        invite = IdeaInvitation(
            idea_id=idea_id, email=email, role=role, invited_by=user.id
        )
        session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return CollaboratorOut(
        status="pending", role=role, email=email, invite_id=invite.id
    )


@router.delete(
    "/{idea_id}/collaborators/{target_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_collaborator(
    idea_id: int,
    target_user_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Owner removes a collaborator, or a collaborator removes themselves (leave)."""
    idea, role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if role != "owner" and target_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    collab = (
        await session.execute(
            select(IdeaCollaborator).where(
                IdeaCollaborator.idea_id == idea_id,
                IdeaCollaborator.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if collab is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collaborator not found"
        )
    await session.delete(collab)
    await session.commit()
    await notify_board([target_user_id])
    await notify_idea(session, idea_id, "updated")


@router.delete(
    "/{idea_id}/invitations/{invite_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def cancel_invitation(
    idea_id: int,
    invite_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_owner(idea_id, user, session)
    invite = await session.get(IdeaInvitation, invite_id)
    if invite is None or invite.idea_id != idea_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    await session.delete(invite)
    await session.commit()
