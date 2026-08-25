"""The GitHub webhook receiver.

Everything else in the app finds out about GitHub by asking. That means an
issue closed on GitHub is invisible until somebody opens the tile, which on a
board of tiles can be weeks. These tests cover the other direction: GitHub
tells us, the board changes, and it changes for everyone who can see it.

The endpoint is public, so the first two tests are the important ones — an
unsigned request must not be able to write into anybody's board.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
import respx

from app.config import settings

BASE = "https://api.github.com"
REPO = "octocat/hello"
CONTENTS = f"{BASE}/repos/{REPO}/contents/IDEA.md"
ROOT = f"{BASE}/repos/{REPO}/contents/"
ISSUES = f"{BASE}/repos/{REPO}/issues"
SECRET = "webhook-secret"


@pytest.fixture
def webhooks_enabled(monkeypatch):
    monkeypatch.setattr(settings, "github_webhook_secret", SECRET)
    return SECRET


def _signed(payload: dict, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": f"sha256={digest}"}


async def _post(client, event: str, payload: dict, *, secret: str = SECRET):
    body, headers = _signed(payload, secret)
    return await client.post(
        "/api/webhooks/github",
        content=body,
        headers={**headers, "X-GitHub-Event": event, "Content-Type": "application/json"},
    )


def _file(text: str, sha: str = "sha-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": base64.b64encode(text.encode()).decode(),
            "sha": sha,
            "type": "file",
        },
    )


async def _idea_with_issue_todo(client, issues: list[dict] | None = None) -> int:
    """An idea whose IDEA.md binds a to-do to issue #12."""
    respx.get(CONTENTS).mock(
        return_value=_file("# Repo idea\n\n## Todos\n\n- [ ] Build MVP (#12)\n")
    )
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=[]))
    respx.put(CONTENTS).mock(
        return_value=httpx.Response(200, json={"content": {"sha": "push-sha"}})
    )
    respx.get(ISSUES).mock(
        return_value=httpx.Response(
            200,
            json=issues
            if issues is not None
            else [
                {
                    "number": 12,
                    "title": "Build MVP",
                    "state": "open",
                    "html_url": f"https://github.com/{REPO}/issues/12",
                }
            ],
        )
    )
    resp = await client.post(
        "/api/ideas", json={"title": "Repo idea", "github_repo": REPO}
    )
    return resp.json()["id"]


async def _todos(idea_id: int) -> list:
    """Read the to-dos straight from the database.

    Going back through the API would re-pull from GitHub, and the pull is
    authoritative — it would answer with the mocked listing rather than with
    what the webhook wrote, which is the thing under test.
    """
    from app.db import SessionLocal
    from app.models import Todo
    from sqlalchemy import select

    async with SessionLocal() as s:
        return list(
            (
                await s.execute(
                    select(Todo).where(Todo.idea_id == idea_id).order_by(Todo.position)
                )
            )
            .scalars()
            .all()
        )


def _issue_event(action: str, **kw) -> dict:
    return {
        "action": action,
        "repository": {"full_name": REPO, "default_branch": "main"},
        "issue": {
            "number": kw.get("number", 12),
            "title": kw.get("title", "Build MVP"),
            "state": kw.get("state", "open"),
            "html_url": f"https://github.com/{REPO}/issues/12",
            "labels": [{"name": n} for n in kw.get("labels", ())],
            "comments": kw.get("comments", 0),
            **({"assignee": {"login": kw["assignee"]}} if kw.get("assignee") else {}),
        },
    }


# ---- authentication ----


@pytest.mark.asyncio
async def test_without_a_secret_the_endpoint_refuses_to_run(anon_client):
    """An unauthenticated writer into people's boards is not a default."""
    resp = await _post(anon_client, "issues", _issue_event("closed"))
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_a_wrong_signature_is_rejected(anon_client, webhooks_enabled):
    resp = await _post(
        anon_client, "issues", _issue_event("closed"), secret="not-the-secret"
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_an_unsigned_request_is_rejected(anon_client, webhooks_enabled):
    resp = await anon_client.post(
        "/api/webhooks/github",
        json=_issue_event("closed"),
        headers={"X-GitHub-Event": "issues"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ping_is_answered(anon_client, webhooks_enabled):
    resp = await _post(anon_client, "ping", {"zen": "Anything added dilutes everything"})
    assert resp.status_code == 200 and resp.json()["handled"] is True


# ---- issues ----


@pytest.mark.asyncio
@respx.mock
async def test_an_issue_closed_on_github_ticks_the_todo(
    users, make_client, anon_client, webhooks_enabled
):
    client = make_client(users["a"])
    idea_id = await _idea_with_issue_todo(client)
    assert (await client.get(f"/api/ideas/{idea_id}")).json()["todos"][0]["done"] is False

    resp = await _post(anon_client, "issues", _issue_event("closed", state="closed"))
    assert resp.status_code == 200
    assert resp.json() == {"event": "issues", "handled": True, "ideas": 1}
    assert (await _todos(idea_id))[0].done is True


@pytest.mark.asyncio
@respx.mock
async def test_labels_and_assignee_arrive_with_the_event(
    users, make_client, anon_client, webhooks_enabled
):
    client = make_client(users["a"])
    idea_id = await _idea_with_issue_todo(client)
    await _post(
        anon_client,
        "issues",
        _issue_event("labeled", labels=["bug"], assignee="octocat", comments=2),
    )
    todo = (await _todos(idea_id))[0]
    assert todo.github_issue_labels == ["bug"]
    assert todo.github_issue_assignee == "octocat"
    assert todo.github_issue_comments == 2


@pytest.mark.asyncio
@respx.mock
async def test_a_comment_updates_the_count(
    users, make_client, anon_client, webhooks_enabled
):
    client = make_client(users["a"])
    idea_id = await _idea_with_issue_todo(client)
    await _post(
        anon_client, "issue_comment", {**_issue_event("created", comments=5), "comment": {}}
    )
    assert (await _todos(idea_id))[0].github_issue_comments == 5


@pytest.mark.asyncio
@respx.mock
async def test_a_deleted_issue_leaves_the_todo_behind_unbound(
    users, make_client, anon_client, webhooks_enabled
):
    """Deleting an issue must not delete somebody's to-do along with it."""
    client = make_client(users["a"])
    idea_id = await _idea_with_issue_todo(client)
    await _post(anon_client, "issues", _issue_event("deleted"))

    todos = await _todos(idea_id)
    assert [t.text for t in todos] == ["Build MVP"]
    assert todos[0].github_issue_number is None


@pytest.mark.asyncio
@respx.mock
async def test_an_event_for_a_repo_nobody_links_is_a_no_op(
    anon_client, webhooks_enabled
):
    payload = _issue_event("closed")
    payload["repository"]["full_name"] = "someone/else"
    resp = await _post(anon_client, "issues", payload)
    assert resp.json()["ideas"] == 0


@pytest.mark.asyncio
async def test_an_event_we_take_no_interest_in_is_acknowledged(
    anon_client, webhooks_enabled
):
    resp = await _post(anon_client, "star", {"repository": {"full_name": REPO}})
    assert resp.status_code == 200 and resp.json()["handled"] is False


# ---- push ----


@pytest.mark.asyncio
@respx.mock
async def test_a_push_touching_the_idea_file_pulls_it(
    users, make_client, anon_client, webhooks_enabled
):
    client = make_client(users["a"])
    idea_id = await _idea_with_issue_todo(client)

    respx.get(CONTENTS).mock(
        return_value=_file(
            "---\nstatus: done\n---\n\n# Renamed on GitHub\n\n## Todos\n", sha="sha-9"
        )
    )
    resp = await _post(
        anon_client,
        "push",
        {
            "ref": "refs/heads/main",
            "repository": {"full_name": REPO, "default_branch": "main"},
            "commits": [{"modified": ["IDEA.md"]}],
        },
    )
    assert resp.json()["ideas"] == 1
    # Straight from the database: the pull already happened.
    from app.db import SessionLocal
    from app.models import Idea

    async with SessionLocal() as s:
        idea = await s.get(Idea, idea_id)
        assert idea.title == "Renamed on GitHub"
        assert idea.status == "done"


@pytest.mark.asyncio
@respx.mock
async def test_a_push_that_changes_nothing_on_the_tile_costs_nothing(
    users, make_client, anon_client, webhooks_enabled
):
    client = make_client(users["a"])
    await _idea_with_issue_todo(client)
    contents = respx.get(CONTENTS)
    before = len(contents.calls)
    resp = await _post(
        anon_client,
        "push",
        {
            "ref": "refs/heads/main",
            "repository": {"full_name": REPO, "default_branch": "main"},
            "commits": [{"modified": ["src/main.py"]}],
        },
    )
    assert resp.json()["ideas"] == 0
    assert len(contents.calls) == before, "ordinary development is not a tile change"


@pytest.mark.asyncio
@respx.mock
async def test_a_push_to_another_branch_is_ignored(
    users, make_client, anon_client, webhooks_enabled
):
    """A tile follows the default branch; unmerged work is not the idea."""
    client = make_client(users["a"])
    await _idea_with_issue_todo(client)
    resp = await _post(
        anon_client,
        "push",
        {
            "ref": "refs/heads/feature",
            "repository": {"full_name": REPO, "default_branch": "main"},
            "commits": [{"modified": ["IDEA.md"]}],
        },
    )
    assert resp.json()["ideas"] == 0
