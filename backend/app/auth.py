from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import IdeaCollaborator, IdeaInvitation, User

SESSION_USER_KEY = "user_id"

oauth = OAuth()
if settings.auth_enabled:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=settings.google_metadata_url,
        client_kwargs={"scope": "openid email profile"},
    )


async def upsert_user(
    session: AsyncSession,
    *,
    google_sub: str,
    email: str,
    name: str | None,
    avatar_url: str | None,
) -> User:
    """Create or update a user keyed by their Google subject id."""
    result = await session.execute(
        select(User).where(User.google_sub == google_sub)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(google_sub=google_sub, email=email, name=name, avatar_url=avatar_url)
        session.add(user)
    else:
        user.email = email
        user.name = name
        user.avatar_url = avatar_url
    await session.commit()
    await session.refresh(user)
    await claim_invitations(session, user)
    return user


async def claim_invitations(session: AsyncSession, user: User) -> None:
    """Turn any pending email invites for this user into real collaborator rows."""
    if not user.email:
        return
    invites = (
        await session.execute(
            select(IdeaInvitation).where(
                func.lower(IdeaInvitation.email) == user.email.lower()
            )
        )
    ).scalars().all()
    if not invites:
        return
    # Append shared ideas after the user's current board.
    max_pos = await session.scalar(
        select(func.coalesce(func.max(IdeaCollaborator.position), -1)).where(
            IdeaCollaborator.user_id == user.id
        )
    )
    next_pos = (max_pos if max_pos is not None else -1) + 1
    for inv in invites:
        exists = await session.scalar(
            select(IdeaCollaborator.id).where(
                IdeaCollaborator.idea_id == inv.idea_id,
                IdeaCollaborator.user_id == user.id,
            )
        )
        if exists is None:
            session.add(
                IdeaCollaborator(
                    idea_id=inv.idea_id,
                    user_id=user.id,
                    role=inv.role,
                    position=next_pos,
                )
            )
            next_pos += 1
        await session.delete(inv)
    await session.commit()


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the logged-in user from the session cookie, or raise 401."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    user = await session.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user
