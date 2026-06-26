import pytest


@pytest.mark.asyncio
async def test_health(anon_client):
    r = await anon_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_me_requires_auth(anon_client):
    r = await anon_client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dev_login_sets_session(anon_client):
    # Auth disabled in tests -> /login uses the dev fallback and sets a cookie.
    r = await anon_client.get("/api/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    me = await anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dev@localhost"
