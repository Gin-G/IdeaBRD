from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User

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
    return user


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
