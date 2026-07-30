"""Tile logos as repo content: idea_logo.<ext> next to IDEA.md."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from tests.test_logo import PNG

BASE = "https://api.github.com"
REPO = "octocat/hello"
IDEA_FILE = f"{BASE}/repos/{REPO}/contents/IDEA.md"
ROOT = f"{BASE}/repos/{REPO}/contents/"
LOGO_PNG = f"{BASE}/repos/{REPO}/contents/idea_logo.png"
LOGO_GIF = f"{BASE}/repos/{REPO}/contents/idea_logo.gif"

GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _idea_file(text: str = "# Repo idea", sha: str = "idea-sha") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": base64.b64encode(text.encode()).decode(),
            "sha": sha,
            "type": "file",
        },
    )


def _root(*files: tuple[str, str, int]) -> httpx.Response:
    """Root directory listing of (name, sha, size) entries."""
    return httpx.Response(
        200,
        json=[
            {"name": name, "sha": sha, "size": size, "type": "file"}
            for name, sha, size in files
        ],
    )


def _blob(data: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        json={"content": base64.b64encode(data).decode(), "encoding": "base64"},
    )


def _pushed_bytes(request: httpx.Request) -> bytes:
    return base64.b64decode(json.loads(request.read())["content"])


async def _tracked_idea(client) -> int:
    """A repo-linked idea whose IDEA.md exists, so pushes are unblocked."""
    respx.get(IDEA_FILE).mock(return_value=_idea_file())
    respx.get(ROOT).mock(return_value=_root())
    resp = await client.post(
        "/api/ideas", json={"title": "Repo idea", "github_repo": REPO}
    )
    assert resp.status_code == 201
    assert resp.json()["git_file_missing"] is False
    return resp.json()["id"]


@pytest.mark.asyncio
@respx.mock
async def test_upload_commits_the_logo_to_the_repo(users, make_client):
    async with make_client(users["a"]) as c:
        idea_id = await _tracked_idea(c)
        put = respx.put(LOGO_PNG).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "logo-sha"}})
        )

        resp = await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )
        assert resp.status_code == 200
        assert resp.json()["git_sync_error"] is None
        assert put.called
        assert _pushed_bytes(put.calls.last.request) == PNG
        assert "IdeaBRD" in json.loads(put.calls.last.request.read())["message"]


@pytest.mark.asyncio
@respx.mock
async def test_upload_does_not_commit_to_an_untracked_repo(users, make_client):
    """Uploading an image must not create files in a repo nobody opted into."""
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=httpx.Response(404, json={}))
        respx.get(ROOT).mock(return_value=_root())
        resp = await c.post(
            "/api/ideas", json={"title": "Untracked", "github_repo": REPO}
        )
        idea_id = resp.json()["id"]
        assert resp.json()["git_file_missing"] is True
        put = respx.put(LOGO_PNG).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "nope"}})
        )

        resp = await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )
        assert resp.status_code == 200
        assert resp.json()["logo_url"] is not None  # still set on the tile
        assert not put.called


@pytest.mark.asyncio
@respx.mock
async def test_linking_a_repo_adopts_its_logo(users, make_client):
    """The point of the feature: a repo carrying idea_logo.png builds the tile."""
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=_idea_file())
        respx.get(ROOT).mock(
            return_value=_root(("idea_logo.png", "blob-sha", len(PNG)))
        )
        respx.get(f"{BASE}/repos/{REPO}/git/blobs/blob-sha").mock(
            return_value=_blob(PNG)
        )

        resp = await c.post(
            "/api/ideas", json={"title": "Adopted", "github_repo": REPO}
        )
        assert resp.status_code == 201
        idea_id = resp.json()["id"]
        assert resp.json()["logo_url"] == f"/api/ideas/{idea_id}/logo?v=blob-sha"

        served = await c.get(f"/api/ideas/{idea_id}/logo")
        assert served.status_code == 200
        assert served.content == PNG
        assert served.headers["content-type"] == "image/png"


@pytest.mark.asyncio
@respx.mock
async def test_unchanged_logo_is_not_refetched(users, make_client):
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=_idea_file())
        respx.get(ROOT).mock(
            return_value=_root(("idea_logo.png", "blob-sha", len(PNG)))
        )
        blob = respx.get(f"{BASE}/repos/{REPO}/git/blobs/blob-sha").mock(
            return_value=_blob(PNG)
        )
        resp = await c.post("/api/ideas", json={"title": "A", "github_repo": REPO})
        idea_id = resp.json()["id"]
        assert blob.call_count == 1

        await c.get(f"/api/ideas/{idea_id}")
        assert blob.call_count == 1  # sha unchanged: the image is not downloaded


@pytest.mark.asyncio
@respx.mock
async def test_logo_deleted_in_git_clears_the_tile(users, make_client):
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=_idea_file())
        respx.get(ROOT).mock(
            return_value=_root(("idea_logo.png", "blob-sha", len(PNG)))
        )
        respx.get(f"{BASE}/repos/{REPO}/git/blobs/blob-sha").mock(
            return_value=_blob(PNG)
        )
        resp = await c.post("/api/ideas", json={"title": "A", "github_repo": REPO})
        idea_id = resp.json()["id"]
        assert resp.json()["logo_url"] is not None

        respx.get(ROOT).mock(return_value=_root())
        resp = await c.get(f"/api/ideas/{idea_id}")
        assert resp.json()["logo_url"] is None
        assert (await c.get(f"/api/ideas/{idea_id}/logo")).status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_app_only_logo_survives_a_pull(users, make_client):
    """A logo git never had must not be wiped by a repo that has no logo file."""
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=httpx.Response(404, json={}))
        respx.get(ROOT).mock(return_value=_root())
        resp = await c.post("/api/ideas", json={"title": "A", "github_repo": REPO})
        idea_id = resp.json()["id"]
        await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )

        resp = await c.get(f"/api/ideas/{idea_id}")
        assert resp.json()["logo_url"] is not None


@pytest.mark.asyncio
@respx.mock
async def test_opting_in_commits_a_logo_uploaded_beforehand(users, make_client):
    """Adding IDEA.md takes the already-uploaded image with it."""
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=httpx.Response(404, json={}))
        respx.get(ROOT).mock(return_value=_root())
        resp = await c.post("/api/ideas", json={"title": "A", "github_repo": REPO})
        idea_id = resp.json()["id"]
        await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )

        respx.put(IDEA_FILE).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "seed-sha"}})
        )
        logo_put = respx.put(LOGO_PNG).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "logo-sha"}})
        )
        resp = await c.post(f"/api/ideas/{idea_id}/sync?init=true")
        assert resp.status_code == 200
        assert resp.json()["git_sync_error"] is None
        assert _pushed_bytes(logo_put.calls.last.request) == PNG


@pytest.mark.asyncio
@respx.mock
async def test_removing_the_logo_commits_the_deletion(users, make_client):
    async with make_client(users["a"]) as c:
        idea_id = await _tracked_idea(c)
        respx.put(LOGO_PNG).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "logo-sha"}})
        )
        await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )
        delete = respx.delete(LOGO_PNG).mock(return_value=httpx.Response(200, json={}))

        resp = await c.delete(f"/api/ideas/{idea_id}/logo")
        assert resp.status_code == 200
        assert resp.json()["logo_url"] is None
        assert delete.called
        assert json.loads(delete.calls.last.request.read())["sha"] == "logo-sha"


@pytest.mark.asyncio
@respx.mock
async def test_changing_format_removes_the_old_file(users, make_client):
    """One logo per repo: a png replaced by a gif leaves no orphan png behind."""
    async with make_client(users["a"]) as c:
        idea_id = await _tracked_idea(c)
        respx.put(LOGO_PNG).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "png-sha"}})
        )
        await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )

        respx.put(LOGO_GIF).mock(
            return_value=httpx.Response(201, json={"content": {"sha": "gif-sha"}})
        )
        respx.get(ROOT).mock(
            return_value=_root(
                ("idea_logo.png", "png-sha", len(PNG)),
                ("idea_logo.gif", "gif-sha", len(GIF)),
            )
        )
        removed = respx.delete(LOGO_PNG).mock(return_value=httpx.Response(200, json={}))

        resp = await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.gif", GIF, "image/gif")}
        )
        assert resp.status_code == 200
        assert removed.called
        assert json.loads(removed.calls.last.request.read())["sha"] == "png-sha"


@pytest.mark.asyncio
@respx.mock
async def test_oversized_repo_logo_is_skipped(users, make_client):
    """A repo image too big to serve back leaves the tile untouched."""
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=_idea_file())
        respx.get(ROOT).mock(
            return_value=_root(("idea_logo.png", "huge-sha", 5 * 1024 * 1024))
        )
        blob = respx.get(f"{BASE}/repos/{REPO}/git/blobs/huge-sha").mock(
            return_value=_blob(PNG)
        )

        resp = await c.post("/api/ideas", json={"title": "A", "github_repo": REPO})
        assert resp.json()["logo_url"] is None
        assert not blob.called


@pytest.mark.asyncio
@respx.mock
async def test_logo_sync_failure_is_reported_not_fatal(users, make_client):
    async with make_client(users["a"]) as c:
        respx.get(IDEA_FILE).mock(return_value=_idea_file())
        respx.get(ROOT).mock(return_value=httpx.Response(403, json={"message": "nope"}))

        resp = await c.post("/api/ideas", json={"title": "A", "github_repo": REPO})
        assert resp.status_code == 201
        assert "rate limit" in resp.json()["git_sync_error"]
