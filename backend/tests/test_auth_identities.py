import pytest

from app.auth import login_with_identity
from app.db import SessionLocal
from app.models import Identity, User
from sqlalchemy import func, select


async def _identities(user_id):
    async with SessionLocal() as s:
        rows = (
            await s.execute(select(Identity).where(Identity.user_id == user_id))
        ).scalars().all()
        return {(i.provider, i.subject) for i in rows}


@pytest.mark.asyncio
async def test_github_autolinks_to_google_by_verified_email(db):
    async with SessionLocal() as s:
        go = await login_with_identity(
            s,
            provider="google",
            subject="g-1",
            email="dev@example.com",
            email_verified=True,
            name="Dev",
        )
        google_user_id = go.id

    async with SessionLocal() as s:
        gh = await login_with_identity(
            s,
            provider="github",
            subject="gh-99",
            email="dev@example.com",
            email_verified=True,
            github_login="devhub",
            github_token="tok",
        )

    # Same user — both identities linked, GitHub token stored.
    assert gh.id == google_user_id
    assert await _identities(google_user_id) == {("google", "g-1"), ("github", "gh-99")}
    async with SessionLocal() as s:
        tok = await s.scalar(
            select(Identity.github_token).where(Identity.provider == "github")
        )
        assert tok == "tok"
        # only one user exists
        assert await s.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.asyncio
async def test_unverified_email_does_not_autolink(db):
    async with SessionLocal() as s:
        go = await login_with_identity(
            s, provider="google", subject="g-2", email="x@example.com",
            email_verified=True, name="X",
        )
        gid = go.id
    async with SessionLocal() as s:
        gh = await login_with_identity(
            s, provider="github", subject="gh-2", email="x@example.com",
            email_verified=False, github_login="x",
        )
    # Different users — no auto-link without a verified email.
    assert gh.id != gid


@pytest.mark.asyncio
async def test_explicit_link_when_emails_differ(db):
    async with SessionLocal() as s:
        go = await login_with_identity(
            s, provider="google", subject="g-3", email="work@example.com",
            email_verified=True,
        )
        gid = go.id
    # User connects GitHub (different email) while logged in -> link_to_user_id.
    async with SessionLocal() as s:
        gh = await login_with_identity(
            s, provider="github", subject="gh-3", email="personal@other.com",
            email_verified=True, github_login="me", link_to_user_id=gid,
        )
    assert gh.id == gid
    assert await _identities(gid) == {("google", "g-3"), ("github", "gh-3")}


@pytest.mark.asyncio
async def test_returning_login_updates_token(db):
    async with SessionLocal() as s:
        await login_with_identity(
            s, provider="github", subject="gh-4", email="a@b.com",
            email_verified=True, github_login="a", github_token="old",
        )
    async with SessionLocal() as s:
        u = await login_with_identity(
            s, provider="github", subject="gh-4", email="a@b.com",
            email_verified=True, github_login="a", github_token="new",
        )
    async with SessionLocal() as s:
        tok = await s.scalar(
            select(Identity.github_token).where(Identity.subject == "gh-4")
        )
        assert tok == "new"


@pytest.mark.asyncio
async def test_unlink_endpoint(db, anon_client):
    # dev login creates a google identity
    await anon_client.get("/api/auth/login", follow_redirects=False)
    me = (await anon_client.get("/api/auth/me")).json()
    ids = (await anon_client.get("/api/auth/identities")).json()
    assert [i["provider"] for i in ids] == ["google"]
    # cannot unlink the only identity
    r = await anon_client.delete("/api/auth/identities/google")
    assert r.status_code == 400

    # add a github identity to this user, then unlink it
    async with SessionLocal() as s:
        s.add(Identity(user_id=me["id"], provider="github", subject="gh-x", github_login="x"))
        await s.commit()
    r = await anon_client.delete("/api/auth/identities/github")
    assert r.status_code == 204
    ids = (await anon_client.get("/api/auth/identities")).json()
    assert [i["provider"] for i in ids] == ["google"]
