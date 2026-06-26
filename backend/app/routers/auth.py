from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SESSION_USER_KEY, get_current_user, oauth, upsert_user
from app.config import settings
from app.db import get_session
from app.models import User
from app.schemas import UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """Begin the Google OIDC flow (or a dev login when Google isn't configured)."""
    if not settings.auth_enabled:
        # Dev fallback: no Google credentials configured. Log in a single local user.
        session: AsyncSession
        async for session in get_session():
            user = await upsert_user(
                session,
                google_sub="dev-local-user",
                email="dev@localhost",
                name="Local Dev",
                avatar_url=None,
            )
            request.session[SESSION_USER_KEY] = user.id
            break
        return RedirectResponse(url=settings.frontend_url)

    return await oauth.google.authorize_redirect(request, settings.oauth_redirect_url)


@router.get("/callback")
async def callback(
    request: Request, session: AsyncSession = Depends(get_session)
):
    """Handle the OIDC redirect: exchange the code, upsert the user, set the cookie."""
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="OIDC not configured")

    token = await oauth.google.authorize_access_token(request)
    claims = token.get("userinfo") or {}
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing subject claim"
        )
    user = await upsert_user(
        session,
        google_sub=sub,
        email=claims.get("email", ""),
        name=claims.get("name"),
        avatar_url=claims.get("picture"),
    )
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse(url=settings.frontend_url)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
