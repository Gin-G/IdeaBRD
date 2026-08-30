"""The one-tap sign-in the Android app uses.

The phone cannot hold a GitHub client secret, so the server does the OAuth
exchange and hands the token back over an Android App Link. What crosses that
link is a one-time code; collecting the token needs the secret the app kept.
These are the properties that make that safe to put in a URL.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import AndroidHandoff, Identity

VERIFIER = "a-secret-the-phone-generated-and-never-sent"


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def make_handoff(user_id: int, *, code: str = "handoff-code", **kwargs) -> None:
    async with SessionLocal() as s:
        s.add(
            AndroidHandoff(
                code=code,
                challenge=kwargs.get("challenge", challenge_for(VERIFIER)),
                user_id=user_id,
                expires_at=kwargs.get(
                    "expires_at", datetime.now(timezone.utc) + timedelta(minutes=10)
                ),
            )
        )
        await s.commit()


async def give_token(user_id: int, token: str = "gho_from_the_server") -> None:
    """A GitHub identity is what actually carries the token."""
    async with SessionLocal() as s:
        s.add(
            Identity(
                user_id=user_id,
                provider="github",
                subject=str(user_id),
                github_token=token,
                github_login="octocat",
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_exchange_returns_the_token_to_whoever_holds_the_verifier(
    anon_client, users
):
    await give_token(users["a"])
    await make_handoff(users["a"])

    response = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": VERIFIER},
    )
    assert response.status_code == 200
    assert response.json() == {"token": "gho_from_the_server", "login": "octocat"}


@pytest.mark.asyncio
async def test_the_code_alone_is_worthless(anon_client, users):
    """Whoever intercepts the App Link has the code and not the verifier."""
    await give_token(users["a"])
    await make_handoff(users["a"])

    response = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": "guessed"},
    )
    assert response.status_code == 403
    assert "gho_from_the_server" not in response.text


@pytest.mark.asyncio
async def test_a_wrong_guess_spends_the_code(anon_client, users):
    """One attempt each: a code is not an oracle to hammer."""
    await give_token(users["a"])
    await make_handoff(users["a"])

    await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": "guessed"},
    )
    retry = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": VERIFIER},
    )
    assert retry.status_code == 404


@pytest.mark.asyncio
async def test_a_code_is_single_use(anon_client, users):
    await give_token(users["a"])
    await make_handoff(users["a"])

    first = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": VERIFIER},
    )
    second = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": VERIFIER},
    )
    assert first.status_code == 200
    assert second.status_code == 404


@pytest.mark.asyncio
async def test_an_expired_code_is_refused(anon_client, users):
    await give_token(users["a"])
    await make_handoff(
        users["a"], expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    response = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "handoff-code", "verifier": VERIFIER},
    )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_unknown_code_says_nothing_useful(anon_client, users):
    response = await anon_client.post(
        "/api/auth/android/exchange",
        json={"code": "never-issued", "verifier": VERIFIER},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_start_refuses_a_malformed_challenge(anon_client):
    response = await anon_client.get("/api/auth/android/start?challenge=../../etc")
    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_the_return_page_renders_without_a_code(anon_client):
    """Reached in a browser when the App Link was not claimed."""
    response = await anon_client.get("/api/auth/android/return")
    assert response.status_code == 200
    assert "IdeaBRD" in response.text or "Signed in" in response.text
