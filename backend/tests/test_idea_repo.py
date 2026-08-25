"""Giving a note-only idea a repository of its own.

An idea kept inside a board repo has nowhere for anyone else to link: a board
is one person's, and a directory in it is not a thing a second person can be
given access to. Handing the idea a repo is what sharing now means — so this is
the point where an idea stops being a tile and becomes a project.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from app.models import Identity

BASE = "https://api.github.com"
NEW_REPO = "octocat/my-idea"
CONTENTS = f"{BASE}/repos/{NEW_REPO}/contents/IDEA.md"
ROOT = f"{BASE}/repos/{NEW_REPO}/contents/"


async def _with_github(user_id: int) -> None:
    from app.db import SessionLocal

    async with SessionLocal() as s:
        s.add(
            Identity(
                user_id=user_id,
                provider="github",
                subject="1",
                github_login="octocat",
                github_token="gho_token",
            )
        )
        await s.commit()


def _mock_creation(name: str = "my-idea") -> httpx.Response:
    return respx.post(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            201,
            json={"full_name": f"octocat/{name}", "default_branch": "main"},
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_an_idea_gets_a_repo_and_moves_into_it(users, make_client):
    await _with_github(users["a"])
    client = make_client(users["a"])
    idea_id = (
        await client.post(
            "/api/ideas", json={"title": "My idea", "notes": "the whole thing"}
        )
    ).json()["id"]
    await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "first step"})

    create = _mock_creation()
    respx.get(CONTENTS).mock(return_value=httpx.Response(404, json={}))
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=[]))
    put = respx.put(CONTENTS).mock(
        return_value=httpx.Response(201, json={"content": {"sha": "seed-sha"}})
    )

    resp = await client.post(
        f"/api/ideas/{idea_id}/repo", json={"name": "my-idea", "private": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["github_repo"] == NEW_REPO
    # Seeded in the same breath: an empty repo would be a worse home than none.
    assert body["git_file_missing"] is False
    assert create.called and put.called
    seeded = base64.b64decode(json.loads(put.calls.last.request.read())["content"]).decode()
    assert "# My idea" in seeded
    assert "the whole thing" in seeded
    assert "- [ ] first step" in seeded


@pytest.mark.asyncio
@respx.mock
async def test_the_repo_is_created_where_the_user_asked(users, make_client):
    await _with_github(users["a"])
    client = make_client(users["a"])
    idea_id = (await client.post("/api/ideas", json={"title": "Org idea"})).json()["id"]

    create = respx.post(f"{BASE}/orgs/acme/repos").mock(
        return_value=httpx.Response(
            201, json={"full_name": "acme/org-idea", "default_branch": "main"}
        )
    )
    respx.get(f"{BASE}/repos/acme/org-idea/contents/IDEA.md").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.get(f"{BASE}/repos/acme/org-idea/contents/").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.put(f"{BASE}/repos/acme/org-idea/contents/IDEA.md").mock(
        return_value=httpx.Response(201, json={"content": {"sha": "seed"}})
    )

    resp = await client.post(
        f"/api/ideas/{idea_id}/repo",
        json={"name": "org-idea", "org": "acme", "private": False},
    )
    assert resp.status_code == 200
    assert resp.json()["github_repo"] == "acme/org-idea"
    assert json.loads(create.calls.last.request.read())["private"] is False


@pytest.mark.asyncio
@respx.mock
async def test_an_idea_that_already_lives_somewhere_is_left_alone(users, make_client):
    await _with_github(users["a"])
    client = make_client(users["a"])
    respx.get(f"{BASE}/repos/octocat/hello/contents/IDEA.md").mock(
        return_value=httpx.Response(404, json={})
    )
    respx.get(f"{BASE}/repos/octocat/hello/contents/").mock(
        return_value=httpx.Response(200, json=[])
    )
    idea_id = (
        await client.post(
            "/api/ideas", json={"title": "Linked", "github_repo": "octocat/hello"}
        )
    ).json()["id"]

    resp = await client.post(f"/api/ideas/{idea_id}/repo", json={"name": "second"})
    assert resp.status_code == 400
    assert "already lives" in resp.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_without_a_github_account_there_is_nowhere_to_put_it(users, make_client):
    client = make_client(users["a"])
    idea_id = (await client.post("/api/ideas", json={"title": "Homeless"})).json()["id"]
    resp = await client.post(f"/api/ideas/{idea_id}/repo", json={"name": "homeless"})
    assert resp.status_code == 400
    assert "GitHub" in resp.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_only_the_owner_may_give_an_idea_a_repo(users, make_client):
    await _with_github(users["a"])
    owner = make_client(users["a"])
    idea_id = (await owner.post("/api/ideas", json={"title": "Shared"})).json()["id"]
    await owner.post(
        f"/api/ideas/{idea_id}/collaborators",
        json={"email": "b@example.com", "role": "editor"},
    )
    editor = make_client(users["b"])
    resp = await editor.post(f"/api/ideas/{idea_id}/repo", json={"name": "nope"})
    assert resp.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_a_name_github_refuses_is_reported(users, make_client):
    await _with_github(users["a"])
    client = make_client(users["a"])
    idea_id = (await client.post("/api/ideas", json={"title": "Taken"})).json()["id"]
    respx.post(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            422, json={"errors": [{"message": "name already exists on this account"}]}
        )
    )
    resp = await client.post(f"/api/ideas/{idea_id}/repo", json={"name": "taken"})
    assert resp.status_code == 422
    assert "already exists" in resp.json()["detail"]
