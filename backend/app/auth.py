from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import Identity, IdeaCollaborator, IdeaInvitation, User

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
if settings.github_oauth_enabled:
    oauth.register(
        name="github",
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": settings.github_scope},
    )


async def login_with_identity(
    session: AsyncSession,
    *,
    provider: str,
    subject: str,
    email: str | None,
    email_verified: bool,
    name: str | None = None,
    avatar_url: str | None = None,
    github_login: str | None = None,
    github_token: str | None = None,
    link_to_user_id: int | None = None,
) -> User:
    """Resolve (or create) the user for a federated login.

    - If the (provider, subject) identity exists, return its user.
    - Else if link_to_user_id is given, attach this identity to that user.
    - Else if the email is verified and matches an existing user, auto-link.
    - Else create a new user.
    """
    ident = (
        await session.execute(
            select(Identity).where(
                Identity.provider == provider, Identity.subject == subject
            )
        )
    ).scalar_one_or_none()

    if ident is not None:
        user = await session.get(User, ident.user_id)
        if email:
            ident.email = email
        if github_login:
            ident.github_login = github_login
        if github_token:
            ident.github_token = github_token
        _update_profile(user, email, name, avatar_url)
        await session.commit()
        await session.refresh(user)
        await claim_invitations(session, user)
        return user

    user: User | None = None
    if link_to_user_id is not None:
        user = await session.get(User, link_to_user_id)
    elif email_verified and email:
        user = (
            await session.execute(
                select(User).where(func.lower(User.email) == email.lower())
            )
        ).scalar_one_or_none()

    if user is None:
        user = User(email=email or "", name=name, avatar_url=avatar_url)
        session.add(user)
        await session.flush()
    else:
        _update_profile(user, None, name, avatar_url, only_if_missing=True)

    session.add(
        Identity(
            user_id=user.id,
            provider=provider,
            subject=subject,
            email=email,
            github_login=github_login,
            github_token=github_token,
        )
    )
    await session.commit()
    await session.refresh(user)
    await claim_invitations(session, user)
    return user


def _update_profile(
    user: User,
    email: str | None,
    name: str | None,
    avatar_url: str | None,
    *,
    only_if_missing: bool = False,
) -> None:
    if email:
        user.email = email
    if name and (not only_if_missing or not user.name):
        user.name = name
    if avatar_url and (not only_if_missing or not user.avatar_url):
        user.avatar_url = avatar_url


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
