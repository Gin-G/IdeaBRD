"""An app push landing on a file that moved on GitHub.

Before this, a 409 from the Contents API was answered by fetching the current
blob sha and pushing our render over the top — the sha check exists to catch
exactly this, and the recovery was to defeat it. Anything written on GitHub
between two app edits was gone, with no error and nothing in the history to
suggest it had ever been there.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

BASE = "https://api.github.com"
REPO = "octocat/hello"
CONTENTS = f"{BASE}/repos/{REPO}/contents/IDEA.md"
ROOT = f"{BASE}/repos/{REPO}/contents/"
ISSUES = f"{BASE}/repos/{REPO}/issues"
SEED_SHA = "seed-sha"


def _file_response(text: str, sha: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": base64.b64encode(text.encode()).decode(),
            "sha": sha,
            "type": "file",
        },
    )


def _content_of(request: httpx.Request) -> str:
    return base64.b64decode(json.loads(request.read())["content"]).decode()


async def _tracked_idea(client) -> tuple[int, str]:
    """A repo-linked idea with IDEA.md seeded; returns its id and that file."""
    respx.get(CONTENTS).mock(return_value=httpx.Response(404, json={}))
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=[]))
    seed = respx.put(CONTENTS).mock(
        return_value=httpx.Response(201, json={"content": {"sha": SEED_SHA}})
    )
    resp = await client.post(
        "/api/ideas",
        json={"title": "Repo idea", "notes": "first line", "github_repo": REPO},
    )
    idea_id = resp.json()["id"]
    await client.post(f"/api/ideas/{idea_id}/sync?init=true")
    return idea_id, _content_of(seed.calls.last.request)


def _conflicting_put(new_sha: str = "merged-sha"):
    """A PUT that rejects the recorded sha once, then accepts the merge."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(409, json={"message": "does not match"})
        return httpx.Response(200, json={"content": {"sha": new_sha}})

    respx.put(CONTENTS).mock(side_effect=handler)
    return calls


@pytest.mark.asyncio
@respx.mock
async def test_a_push_merges_instead_of_overwriting(users, make_client):
    client = make_client(users["a"])
    idea_id, base_file = await _tracked_idea(client)

    # Meanwhile, on GitHub: a paragraph added and a to-do written by hand.
    remote = base_file.replace("first line", "first line\nadded on GitHub").replace(
        "## Todos\n", "## Todos\n\n- [ ] written on GitHub\n"
    )
    respx.get(CONTENTS).mock(return_value=_file_response(remote, "remote-sha"))
    respx.get(f"{BASE}/repos/{REPO}/git/blobs/{SEED_SHA}").mock(
        return_value=httpx.Response(
            200,
            json={
                "encoding": "base64",
                "content": base64.b64encode(base_file.encode()).decode(),
            },
        )
    )
    puts = _conflicting_put()

    resp = await client.patch(
        f"/api/ideas/{idea_id}", json={"notes": "first line\nadded in the app"}
    )
    assert resp.status_code == 200

    assert len(puts) == 2, "the conflict is retried once, as a merge"
    pushed = _content_of(puts[1])
    assert "added on GitHub" in pushed, "the repo's paragraph survived our push"
    assert "added in the app" in pushed
    assert "- [ ] written on GitHub" in pushed
    # The retry is against the sha we were told, not the one we had.
    assert json.loads(puts[1].read())["sha"] == "remote-sha"

    # ...and the board holds what was committed, not what it tried to commit.
    data = resp.json()
    assert data["notes"] == "first line\nadded on GitHub\nadded in the app"
    assert [t["text"] for t in data["todos"]] == ["written on GitHub"]


@pytest.mark.asyncio
@respx.mock
async def test_a_deleted_file_is_recreated_rather_than_merged(users, make_client):
    """A 409 on a file that is no longer there isn't a conflict, it's a gap."""
    client = make_client(users["a"])
    idea_id, _ = await _tracked_idea(client)

    respx.get(CONTENTS).mock(return_value=httpx.Response(404, json={}))
    puts = _conflicting_put(new_sha="recreated-sha")

    resp = await client.patch(f"/api/ideas/{idea_id}", json={"notes": "still here"})
    assert resp.status_code == 200
    assert len(puts) == 2
    assert "sha" not in json.loads(puts[1].read()), "a create carries no sha"
    assert "still here" in _content_of(puts[1])


@pytest.mark.asyncio
@respx.mock
async def test_without_the_base_blob_the_merge_keeps_both_sides(users, make_client):
    """A base we can't fetch degrades the merge to a union, never to a loss."""
    client = make_client(users["a"])
    idea_id, base_file = await _tracked_idea(client)

    remote = base_file.replace("## Todos\n", "## Todos\n\n- [ ] theirs\n")
    respx.get(CONTENTS).mock(return_value=_file_response(remote, "remote-sha"))
    respx.get(f"{BASE}/repos/{REPO}/git/blobs/{SEED_SHA}").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    respx.get(ISSUES).mock(return_value=httpx.Response(200, json=[]))
    puts = _conflicting_put()

    resp = await client.post(
        f"/api/ideas/{idea_id}/todos", json={"text": "ours"}
    )
    assert resp.status_code == 201
    pushed = _content_of(puts[-1])
    assert "- [ ] theirs" in pushed and "- [ ] ours" in pushed
