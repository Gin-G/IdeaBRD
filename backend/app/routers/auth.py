from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
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
from app.models import AndroidHandoff, Identity, User
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

    # Started from the phone? Hand the result back through the App Link rather
    # than dropping the browser on the board.
    challenge = request.session.pop(ANDROID_CHALLENGE_KEY, None)
    if challenge:
        code = secrets.token_urlsafe(32)
        session.add(
            AndroidHandoff(
                code=code,
                challenge=challenge,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + ANDROID_HANDOFF_TTL,
            )
        )
        await session.commit()
        return RedirectResponse(
            url=f"{settings.frontend_url}{ANDROID_RETURN_PATH}?code={code}"
        )

    return RedirectResponse(url=settings.frontend_url)


# ---- Android app sign-in ----
#
# The phone has no client secret and cannot be given one: whatever ships in the
# APK ships to everybody. GitHub's device flow is the usual answer to that, but
# it means typing an eight-character code into a page that refuses a paste,
# which on the device doing the signing in is a poor trade.
#
# So the server, which does hold the secret, runs the ordinary redirect flow on
# the app's behalf and hands the result back over an Android App Link. The link
# carries a one-time code, never the token, and redeeming that code needs a
# secret the app generated and never transmitted — it sends only the SHA-256 up
# front. An App Link some other app managed to claim therefore gets nothing.

ANDROID_CHALLENGE_KEY = "android_challenge"
ANDROID_RETURN_PATH = "/api/auth/android/return"
ANDROID_HANDOFF_TTL = timedelta(minutes=10)


def _sha256_b64url(value: str) -> str:
    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


@router.get("/android/start")
async def android_start(request: Request, challenge: str):
    """Begin a sign-in for the Android app. `challenge` is SHA-256 of its secret."""
    if not settings.github_oauth_enabled:
        raise HTTPException(status_code=404, detail="GitHub login not configured")
    if not 16 <= len(challenge) <= 64 or not challenge.replace("-", "").replace(
        "_", ""
    ).isalnum():
        raise HTTPException(status_code=400, detail="Malformed challenge")
    # Ride the browser session through the redirect, the way the state parameter
    # already does. Nothing here is worth a row until the callback knows whether
    # the sign-in succeeded at all.
    request.session[ANDROID_CHALLENGE_KEY] = challenge
    return await oauth.github.authorize_redirect(request, settings.github_redirect_url)


@router.get("/android/return", response_class=HTMLResponse)
async def android_return() -> HTMLResponse:
    """Where the browser lands, and where the App Link takes over.

    Only ever seen when the link was not claimed — an install Android has not
    verified yet, or a browser on a machine without the app — so it says what
    happened rather than showing a blank page.
    """
    return HTMLResponse(
        """<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signed in</title>
<body style="font-family: system-ui, sans-serif; background:#0f172a; color:#e2e8f0;
             display:grid; place-items:center; height:100vh; margin:0; text-align:center">
  <main style="max-width:24rem; padding:1.5rem">
    <h1 style="font-size:1.25rem">Signed in to GitHub</h1>
    <p style="color:#94a3b8; font-size:0.9rem">
      If IdeaBRD did not open by itself, switch back to it — it is waiting.
      You can close this tab.
    </p>
  </main>
</body>"""
    )


@router.post("/android/exchange")
async def android_exchange(
    request: Request, session: AsyncSession = Depends(get_session)
):
    """Trade the one-time code, plus the app's secret, for the GitHub token."""
    body = await request.json()
    code = str(body.get("code") or "")
    verifier = str(body.get("verifier") or "")
    if not code or not verifier:
        raise HTTPException(status_code=400, detail="code and verifier are required")

    handoff = (
        await session.execute(select(AndroidHandoff).where(AndroidHandoff.code == code))
    ).scalar_one_or_none()
    if handoff is None:
        raise HTTPException(status_code=404, detail="No such sign-in")

    # Spent on presentation, whatever happens next: a wrong verifier must not
    # get a second attempt against the same code.
    user_id = handoff.user_id
    # Postgres hands back an aware datetime; SQLite, which the tests run on,
    # does not. Treat a naive one as the UTC it was written as.
    expires_at = handoff.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    expired = expires_at < datetime.now(timezone.utc)
    matches = secrets.compare_digest(_sha256_b64url(verifier), handoff.challenge)
    await session.delete(handoff)
    await session.commit()

    if expired:
        raise HTTPException(status_code=410, detail="That sign-in expired")
    if not matches:
        raise HTTPException(status_code=403, detail="That sign-in was not yours")

    # The token belongs to the GitHub identity, not the user — the same account
    # can be reached through Google as well, and only one of those has a token.
    row = (
        await session.execute(
            select(Identity.github_token, Identity.github_login).where(
                Identity.user_id == user_id,
                Identity.provider == "github",
                Identity.github_token.is_not(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=409, detail="No GitHub token for that account")
    return {"token": row.github_token, "login": row.github_login}


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
