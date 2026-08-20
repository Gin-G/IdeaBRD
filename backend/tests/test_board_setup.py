"""First-run setup: giving a board somewhere to live.

The flow is one step for the user — pick a name, get a repo — so the failures
worth testing are the ones that would otherwise leave a repo created but no
board in it, or a board pointed at a repo that isn't theirs.
"""

import json

import httpx
import pytest
import respx

from app.boardrepo import MARKER_FILE
from tests.test_publisher import REPO, FakeRepo

BASE = "https://api.github.com"


async def _with_github_token(user_id: int, token: str = "gho_test") -> None:
    from app.db import SessionLocal
    from app.models import Identity

    async with SessionLocal() as s:
        s.add(
            Identity(
                user_id=user_id,
                provider="github",
                subject=f"gh-{user_id}",
                github_login="octocat",
                github_token=token,
            )
        )
        await s.commit()


def _user_endpoint(scopes: str) -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(
            200, json={"login": "octocat"}, headers={"X-OAuth-Scopes": scopes}
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_owners_lists_the_user_and_their_orgs(users, make_client):
    await _with_github_token(users["a"])
    _user_endpoint("repo, read:org")
    respx.get(f"{BASE}/user/orgs").mock(
        return_value=httpx.Response(200, json=[{"login": "acme"}, {"login": "widgets"}])
    )

    async with make_client(users["a"]) as c:
        body = (await c.get("/api/board/owners")).json()

    assert body["orgs_visible"] is True
    assert body["owners"] == [
        {"login": "octocat", "kind": "user"},
        {"login": "acme", "kind": "org"},
        {"login": "widgets", "kind": "org"},
    ]


@pytest.mark.asyncio
@respx.mock
async def test_a_token_without_read_org_still_works(users, make_client):
    """Logins made before the app asked for read:org keep working — they just
    can't see organisations, and say so rather than showing an empty list."""
    await _with_github_token(users["a"])
    _user_endpoint("repo")
    orgs = respx.get(f"{BASE}/user/orgs")

    async with make_client(users["a"]) as c:
        body = (await c.get("/api/board/owners")).json()

    assert body["orgs_visible"] is False
    assert body["owners"] == [{"login": "octocat", "kind": "user"}]
    assert not orgs.called, "no point asking for orgs the token cannot see"


@pytest.mark.asyncio
@respx.mock
async def test_owners_needs_a_github_login(users, make_client):
    async with make_client(users["a"]) as c:
        resp = await c.get("/api/board/owners")
    assert resp.status_code == 400
    assert "GitHub" in resp.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_init_creates_an_empty_repo_and_publishes_into_it(users, make_client):
    """The whole migration in one call: a repo that didn't exist, holding the board."""
    from app.db import SessionLocal
    from app.models import Idea

    await _with_github_token(users["a"])
    async with SessionLocal() as s:
        s.add_all(
            [
                Idea(user_id=users["a"], title="IdeaBRD", notes="", position=0),
                Idea(user_id=users["a"], title="Second", notes="", position=1),
            ]
        )
        await s.commit()

    created = respx.post(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            201, json={"full_name": REPO, "default_branch": "main"}
        )
    )
    # GitHub initialises it, so the repo the publisher meets already has a commit.
    repo = FakeRepo({"README.md": b"# board\n"})
    repo.install(respx.mock)

    async with make_client(users["a"]) as c:
        resp = await c.post("/api/board/init", json={"name": "board", "private": True})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["board"]["board_repo"] == REPO
    assert body["publish"]["committed"] is True
    assert set(repo.files) == {
        "README.md",
        MARKER_FILE,
        "ideas/ideabrd/IDEA.md",
        "ideas/second/IDEA.md",
    }
    # The stub GitHub left is replaced by one naming whose board this is.
    assert repo.files["README.md"].startswith(b"# octocat's idea board")
    # Initialised on creation, because a repo with no commits rejects every git
    # data write and could never have a first tree built in it.
    assert json.loads(created.calls[0].request.read())["auto_init"] is True
    # Still one board commit: GitHub's initial commit, then the whole board.
    assert repo.commits == 1


@pytest.mark.asyncio
@respx.mock
async def test_init_under_an_org_targets_the_org_endpoint(users, make_client):
    await _with_github_token(users["a"])
    org_create = respx.post(f"{BASE}/orgs/acme/repos").mock(
        return_value=httpx.Response(
            201, json={"full_name": "acme/board", "default_branch": "trunk"}
        )
    )
    # The publisher talks to the org repo, on its own default branch.
    repo = FakeRepo({"README.md": b"# board\n"}, repo="acme/board")
    repo.install(respx.mock)

    async with make_client(users["a"]) as c:
        resp = await c.post(
            "/api/board/init", json={"name": "board", "org": "acme", "private": True}
        )

    assert resp.status_code == 200, resp.text
    assert org_create.called
    assert resp.json()["board"]["board_repo"] == "acme/board"
    assert resp.json()["board"]["board_branch"] == "trunk"
    assert "ideas/ideabrd/IDEA.md" not in repo.files, "no ideas on this board yet"


@pytest.mark.asyncio
@respx.mock
async def test_init_surfaces_a_name_already_taken(users, make_client):
    """A 422 here is the common case — the user picked a name they already used."""
    await _with_github_token(users["a"])
    respx.post(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            422, json={"errors": [{"message": "name already exists on this account"}]}
        )
    )

    async with make_client(users["a"]) as c:
        resp = await c.post("/api/board/init", json={"name": "board"})

    assert resp.status_code == 422
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
@respx.mock
async def test_a_failed_creation_leaves_the_board_unlinked(users, make_client):
    """Nothing is recorded until the repo actually exists, so a retry is clean."""
    from app.db import SessionLocal
    from app.models import User

    await _with_github_token(users["a"])
    respx.post(f"{BASE}/user/repos").mock(return_value=httpx.Response(403, json={}))

    async with make_client(users["a"]) as c:
        assert (await c.post("/api/board/init", json={"name": "board"})).status_code == 403

    async with SessionLocal() as s:
        assert (await s.get(User, users["a"])).board_repo is None
