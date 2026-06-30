from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    SESSION_USER_KEY,
    get_current_user,
    login_with_identity,
    oauth,
)
from app.config import settings
from app.db import get_session
from app.models import Identity, User
from app.schemas import IdentityOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---- Google ----


@router.get("/login")
@router.get("/google/login")
async def login(request: Request):
    """Begin Google login (or a dev login when Google isn't configured)."""
    if not settings.auth_enabled:
        async for session in get_session():
            user = await login_with_identity(
                session,
                provider="google",
                subject="dev-local-user",
                email="dev@localhost",
                email_verified=True,
                name="Local Dev",
            )
            request.session[SESSION_USER_KEY] = user.id
            break
        return RedirectResponse(url=settings.frontend_url)
    return await oauth.google.authorize_redirect(request, settings.oauth_redirect_url)


@router.get("/callback")
async def callback(request: Request, session: AsyncSession = Depends(get_session)):
    """Google OIDC redirect handler."""
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="OIDC not configured")
    token = await oauth.google.authorize_access_token(request)
    claims = token.get("userinfo") or {}
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="Missing subject claim")
    user = await login_with_identity(
        session,
        provider="google",
        subject=sub,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
        avatar_url=claims.get("picture"),
        link_to_user_id=request.session.pop("link_user_id", None),
    )
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(url=settings.frontend_url)


# ---- GitHub ----


@router.get("/github/login")
async def github_login(request: Request, connect: int = 0):
    """Begin GitHub login. With connect=1 (and logged in) it links to the current user."""
    if not settings.github_oauth_enabled:
        raise HTTPException(status_code=404, detail="GitHub login not configured")
    if connect:
        current = request.session.get(SESSION_USER_KEY)
        if current:
            request.session["link_user_id"] = current
    return await oauth.github.authorize_redirect(request, settings.github_redirect_url)


@router.get("/github/callback")
async def github_callback(
    request: Request, session: AsyncSession = Depends(get_session)
):
    if not settings.github_oauth_enabled:
        raise HTTPException(status_code=404, detail="GitHub login not configured")
    token = await oauth.github.authorize_access_token(request)
    profile = (await oauth.github.get("user", token=token)).json()
    # Primary verified email isn't in /user when private; fetch it explicitly.
    email = profile.get("email")
    email_verified = False
    try:
        emails = (await oauth.github.get("user/emails", token=token)).json()
        primary = next(
            (e for e in emails if e.get("primary") and e.get("verified")), None
        )
        if primary:
            email = primary["email"]
            email_verified = True
    except Exception:
        pass

    user = await login_with_identity(
        session,
        provider="github",
        subject=str(profile["id"]),
        email=email,
        email_verified=email_verified,
        name=profile.get("name") or profile.get("login"),
        avatar_url=profile.get("avatar_url"),
        github_login=profile.get("login"),
        github_token=token.get("access_token"),
        link_to_user_id=request.session.pop("link_user_id", None),
    )
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(url=settings.frontend_url)


# ---- Session / identities ----


@router.get("/providers")
async def providers():
    """Which login methods are available (for the UI). Public."""
    return {
        "google": settings.auth_enabled,
        "github": settings.github_oauth_enabled,
        "dev": not settings.auth_enabled,
    }


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.get("/identities", response_model=list[IdentityOut])
async def list_identities(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(Identity).where(Identity.user_id == user.id)
        )
    ).scalars().all()
    return [
        IdentityOut(
            provider=i.provider,
            email=i.email,
            github_login=i.github_login,
            has_repo_token=bool(i.github_token),
        )
        for i in rows
    ]


@router.delete("/identities/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_identity(
    provider: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(Identity).where(Identity.user_id == user.id)
        )
    ).scalars().all()
    if len(rows) <= 1:
        raise HTTPException(
            status_code=400, detail="Cannot remove your only sign-in method"
        )
    target = next((i for i in rows if i.provider == provider), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    await session.delete(target)
    await session.commit()
