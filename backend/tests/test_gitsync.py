import base64
import json

import httpx
import pytest
import respx

from app.ideafile import parse_idea_file, render_idea_file

BASE = "https://api.github.com"
CONTENTS = f"{BASE}/repos/octocat/hello/contents/IDEA.md"


def _file_response(text: str, sha: str = "sha-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": base64.b64encode(text.encode()).decode(),
            "sha": sha,
            "type": "file",
        },
    )


def _pushed_content(request: httpx.Request) -> str:
    return base64.b64decode(json.loads(request.read())["content"]).decode()


def test_render_parse_round_trip():
    text = render_idea_file(
        title="My idea",
        notes="Some notes.\n\nMore notes.",
        status="active",
        progress=60,
        todos=[("set up repo", True), ("build MVP", False)],
    )
    parsed = parse_idea_file(text)
    assert parsed.title == "My idea"
    assert parsed.notes == "Some notes.\n\nMore notes."
    assert parsed.status == "active"
    assert parsed.progress == 60
    assert parsed.todos == [("set up repo", True), ("build MVP", False)]


def test_parse_lenient():
    # No frontmatter, no title, stray text in the todos section, later section.
    parsed = parse_idea_file(
        "just some notes\n\n## To-Dos\nnot an item\n- [X] shipped\n* [ ] next\n\n## Links\nmore"
    )
    assert parsed.title is None
    assert parsed.status is None
    assert parsed.progress is None
    assert parsed.todos == [("shipped", True), ("next", False)]
    assert "just some notes" in parsed.notes
    assert "## Links" in parsed.notes


def test_parse_bad_frontmatter_values():
    parsed = parse_idea_file("---\nstatus: bogus\nprogress: lots\n---\nbody")
    assert parsed.status is None
    assert parsed.progress is None
    assert parsed.notes == "body"


async def _create_tracked_idea(client, respx_mock) -> int:
    """Create a repo-linked idea and opt in to tracking (seeds IDEA.md)."""
    respx_mock.get(CONTENTS).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    respx_mock.put(CONTENTS).mock(
        return_value=httpx.Response(201, json={"content": {"sha": "seed-sha"}})
    )
    resp = await client.post(
        "/api/ideas",
        json={"title": "Repo idea", "notes": "hello", "github_repo": "octocat/hello"},
    )
    assert resp.status_code == 201
    idea_id = resp.json()["id"]
    resp = await client.post(f"/api/ideas/{idea_id}/sync?init=true")
    assert resp.status_code == 200
    assert resp.json()["git_file_missing"] is False
    return idea_id


@pytest.mark.asyncio
@respx.mock
async def test_create_prompts_instead_of_seeding(users, make_client):
    client = make_client(users["a"])
    respx.get(CONTENTS).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    put_route = respx.put(CONTENTS).mock(
        return_value=httpx.Response(201, json={"content": {"sha": "seed-sha"}})
    )

    resp = await client.post(
        "/api/ideas",
        json={"title": "Repo idea", "notes": "hello", "github_repo": "octocat/hello"},
    )
    assert resp.status_code == 201
    idea_id = resp.json()["id"]
    # No file was committed without the user's opt-in; the UI gets a prompt flag.
    assert resp.json()["git_file_missing"] is True
    assert not put_route.called

    # App edits before opting in must not create the file either.
    resp = await client.patch(f"/api/ideas/{idea_id}", json={"notes": "still local"})
    assert resp.status_code == 200
    assert resp.json()["git_file_missing"] is True
    assert not put_route.called

    # The user confirms: IDEA.md is committed from the idea's current state.
    resp = await client.post(f"/api/ideas/{idea_id}/sync?init=true")
    assert resp.status_code == 200
    assert resp.json()["git_file_missing"] is False
    assert put_route.called
    content = _pushed_content(put_route.calls.last.request)
    assert "# Repo idea" in content
    assert "still local" in content
    assert "IdeaBRD" in json.loads(put_route.calls.last.request.read())["message"]


@pytest.mark.asyncio
@respx.mock
async def test_get_pulls_from_git_and_git_wins(users, make_client):
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    remote = (
        "---\nstatus: done\nprogress: 100\n---\n\n# Renamed from git\n\n"
        "Notes edited on GitHub.\n\n## Todos\n\n- [x] only todo\n"
    )
    respx.get(CONTENTS).mock(return_value=_file_response(remote, sha="sha-2"))

    resp = await client.get(f"/api/ideas/{idea_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Renamed from git"
    assert data["notes"] == "Notes edited on GitHub."
    assert data["status"] == "done"
    assert data["progress"] == 100
    assert [(t["text"], t["done"]) for t in data["todos"]] == [("only todo", True)]
    assert data["git_synced_at"] is not None
    assert data["git_sync_error"] is None


@pytest.mark.asyncio
@respx.mock
async def test_get_adopts_existing_idea_file(users, make_client):
    """Linking a repo that already has an IDEA.md adopts it without prompting."""
    client = make_client(users["a"])
    respx.get(CONTENTS).mock(
        return_value=_file_response("# From the repo\n\nrepo notes", sha="repo-sha")
    )
    resp = await client.post(
        "/api/ideas", json={"title": "temp", "github_repo": "octocat/hello"}
    )
    data = resp.json()
    assert data["git_file_missing"] is False
    assert data["title"] == "From the repo"
    assert data["notes"] == "repo notes"


@pytest.mark.asyncio
@respx.mock
async def test_get_skips_pull_when_sha_unchanged(users, make_client):
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    # Same sha as the seed commit: content must NOT be re-applied.
    respx.get(CONTENTS).mock(return_value=_file_response("# Other title", sha="seed-sha"))
    resp = await client.get(f"/api/ideas/{idea_id}")
    assert resp.json()["title"] == "Repo idea"


@pytest.mark.asyncio
@respx.mock
async def test_patch_pushes_to_git(users, make_client):
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    respx.put(CONTENTS).mock(
        return_value=httpx.Response(200, json={"content": {"sha": "push-sha"}})
    )
    resp = await client.patch(f"/api/ideas/{idea_id}", json={"notes": "new notes"})
    assert resp.status_code == 200
    assert resp.json()["git_sync_error"] is None
    assert "new notes" in _pushed_content(respx.calls.last.request)


@pytest.mark.asyncio
@respx.mock
async def test_todo_change_pushes_to_git(users, make_client):
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    respx.put(CONTENTS).mock(
        return_value=httpx.Response(200, json={"content": {"sha": "todo-sha"}})
    )
    resp = await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "from app"})
    assert resp.status_code == 201
    assert "- [ ] from app" in _pushed_content(respx.calls.last.request)


@pytest.mark.asyncio
@respx.mock
async def test_sync_endpoint_and_error_reporting(users, make_client):
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    respx.get(CONTENTS).mock(
        return_value=httpx.Response(403, json={"message": "rate limited"})
    )
    resp = await client.post(f"/api/ideas/{idea_id}/sync")
    assert resp.status_code == 200
    assert "rate limit" in resp.json()["git_sync_error"]

    # An idea without a repo can't be synced.
    plain = await client.post("/api/ideas", json={"title": "No repo"})
    resp = await client.post(f"/api/ideas/{plain.json()['id']}/sync")
    assert resp.status_code == 400
