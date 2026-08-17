"""To-dos backed by GitHub issues: promotion, two-way state, file round-trip."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from app.ideafile import parse_idea_file, render_idea_file

BASE = "https://api.github.com"
REPO = "octocat/hello"
IDEA_FILE = f"{BASE}/repos/{REPO}/contents/IDEA.md"
ROOT = f"{BASE}/repos/{REPO}/contents/"
ISSUES = f"{BASE}/repos/{REPO}/issues"


def _issue(number: int, title: str, state: str = "open") -> dict:
    return {
        "number": number,
        "title": title,
        "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
    }


def _idea_file(text: str = "# Repo idea", sha: str = "idea-sha") -> httpx.Response:
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


def _mock_repo(*, idea_file: httpx.Response | None = None) -> None:
    """The calls every pull makes: IDEA.md, the root listing, and the file push."""
    respx.get(IDEA_FILE).mock(return_value=idea_file or _idea_file())
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=[]))
    respx.put(IDEA_FILE).mock(
        return_value=httpx.Response(200, json={"content": {"sha": "push-sha"}})
    )


async def _tracked_idea(client) -> int:
    """A repo-linked idea whose IDEA.md already exists, so pushes are unblocked."""
    resp = await client.post(
        "/api/ideas", json={"title": "Repo idea", "github_repo": REPO}
    )
    assert resp.status_code == 201
    assert resp.json()["git_file_missing"] is False
    return resp.json()["id"]


# ---- file format ----


def test_issue_reference_round_trips():
    text = render_idea_file(
        title="T",
        notes="",
        status="active",
        progress=0,
        todos=[("plain item", False), ("issue item", True, 12)],
    )
    assert "- [ ] plain item\n" in text
    assert "- [x] issue item (#12)\n" in text
    assert parse_idea_file(text).todos == [
        ("plain item", False, None),
        ("issue item", True, 12),
    ]


def test_issue_reference_parsing_edge_cases():
    parsed = parse_idea_file(
        "## Todos\n"
        "- [ ] no ref\n"
        "- [ ] spaced   (#7)\n"
        "- [ ] (#9)\n"          # nothing but a reference: stays literal text
        "- [ ] mid (#3) text\n"  # only a trailing ref counts
    )
    assert parsed.todos == [
        ("no ref", False, None),
        ("spaced", False, 7),
        ("(#9)", False, None),
        ("mid (#3) text", False, None),
    ]


# ---- promotion ----


@pytest.mark.asyncio
@respx.mock
async def test_promote_todo_opens_issue_and_records_it(users, make_client):
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)

    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "Build MVP"})
    ).json()
    assert todo["github_issue_number"] is None

    create = respx.post(ISSUES).mock(
        return_value=httpx.Response(201, json=_issue(12, "Build MVP"))
    )
    resp = await client.post(f"/api/todos/{todo['id']}/issue")
    assert resp.status_code == 200
    assert create.called
    assert json.loads(create.calls.last.request.read())["title"] == "Build MVP"

    data = resp.json()
    assert data["github_issue_number"] == 12
    assert data["github_issue_url"].endswith("/issues/12")

    # The reference is committed to IDEA.md so the file carries the binding too.
    assert "- [ ] Build MVP (#12)" in _pushed_content(respx.calls.last.request)


@pytest.mark.asyncio
@respx.mock
async def test_promote_is_idempotent_and_needs_a_repo(users, make_client):
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "once"})
    ).json()

    create = respx.post(ISSUES).mock(
        return_value=httpx.Response(201, json=_issue(5, "once"))
    )
    assert (await client.post(f"/api/todos/{todo['id']}/issue")).status_code == 200
    assert create.call_count == 1
    # Promoting again returns the existing link rather than opening a duplicate.
    resp = await client.post(f"/api/todos/{todo['id']}/issue")
    assert resp.status_code == 200
    assert resp.json()["github_issue_number"] == 5
    assert create.call_count == 1

    # An idea with no repo has nowhere to file an issue.
    plain = (await client.post("/api/ideas", json={"title": "No repo"})).json()
    other = (
        await client.post(f"/api/ideas/{plain['id']}/todos", json={"text": "x"})
    ).json()
    resp = await client.post(f"/api/todos/{other['id']}/issue")
    assert resp.status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_promote_reports_github_failure(users, make_client):
    """An explicit action that fails must say so — unlike background syncs."""
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "nope"})
    ).json()

    respx.post(ISSUES).mock(
        return_value=httpx.Response(410, json={"message": "Issues are disabled"})
    )
    resp = await client.post(f"/api/todos/{todo['id']}/issue")
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"].lower()

    # The to-do is untouched: no half-promoted row left behind.
    todos = (await client.get(f"/api/ideas/{idea_id}/todos")).json()
    assert todos[0]["github_issue_number"] is None


# ---- two-way state ----


@pytest.mark.asyncio
@respx.mock
async def test_ticking_a_promoted_todo_closes_the_issue(users, make_client):
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "Ship it"})
    ).json()
    respx.post(ISSUES).mock(return_value=httpx.Response(201, json=_issue(3, "Ship it")))
    await client.post(f"/api/todos/{todo['id']}/issue")

    patch = respx.patch(f"{ISSUES}/3").mock(
        return_value=httpx.Response(200, json=_issue(3, "Ship it", "closed"))
    )
    resp = await client.patch(f"/api/todos/{todo['id']}", json={"done": True})
    assert resp.status_code == 200
    assert patch.called
    assert json.loads(patch.calls.last.request.read())["state"] == "closed"

    # Reordering alone leaves the issue alone.
    patch.reset()
    await client.patch(f"/api/todos/{todo['id']}", json={"position": 3})
    assert not patch.called


@pytest.mark.asyncio
@respx.mock
async def test_pull_lets_the_issue_win_over_the_file(users, make_client):
    """The issue owns a promoted item's title and state, not IDEA.md's checkbox."""
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "old title"})
    ).json()
    respx.post(ISSUES).mock(
        return_value=httpx.Response(201, json=_issue(8, "old title"))
    )
    await client.post(f"/api/todos/{todo['id']}/issue")

    # The file still says open with the old wording; the issue says otherwise.
    respx.get(IDEA_FILE).mock(
        return_value=_idea_file(
            "# Repo idea\n\n## Todos\n\n- [ ] old title (#8)\n", sha="sha-2"
        )
    )
    respx.get(ISSUES).mock(
        return_value=httpx.Response(
            200, json=[_issue(8, "renamed on github", "closed")]
        )
    )

    data = (await client.get(f"/api/ideas/{idea_id}")).json()
    assert [(t["text"], t["done"]) for t in data["todos"]] == [
        ("renamed on github", True)
    ]
    # Same row, not a delete-plus-insert: the number matched where the text didn't.
    assert data["todos"][0]["id"] == todo["id"]


@pytest.mark.asyncio
@respx.mock
async def test_pull_ignores_pull_requests_and_unknown_issues(users, make_client):
    """The issues endpoint also returns PRs; a PR must never drive a to-do."""
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "keep open"})
    ).json()
    respx.post(ISSUES).mock(
        return_value=httpx.Response(201, json=_issue(4, "keep open"))
    )
    await client.post(f"/api/todos/{todo['id']}/issue")

    # Number 4 comes back as a merged PR, plus an issue we don't track.
    respx.get(IDEA_FILE).mock(
        return_value=_idea_file(
            "# Repo idea\n\n## Todos\n\n- [ ] keep open (#4)\n", sha="sha-3"
        )
    )
    respx.get(ISSUES).mock(
        return_value=httpx.Response(
            200,
            json=[
                {**_issue(4, "some PR", "closed"), "pull_request": {"url": "..."}},
                _issue(99, "unrelated", "closed"),
            ],
        )
    )

    data = (await client.get(f"/api/ideas/{idea_id}")).json()
    assert [(t["text"], t["done"]) for t in data["todos"]] == [("keep open", False)]


@pytest.mark.asyncio
@respx.mock
async def test_hand_written_reference_adopts_the_existing_todo(users, make_client):
    """Adding "(#N)" by hand in IDEA.md binds the to-do instead of duplicating it."""
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "by hand"})
    ).json()

    respx.get(IDEA_FILE).mock(
        return_value=_idea_file(
            "# Repo idea\n\n## Todos\n\n- [ ] by hand (#21)\n", sha="sha-4"
        )
    )
    respx.get(ISSUES).mock(
        return_value=httpx.Response(200, json=[_issue(21, "by hand")])
    )

    todos = (await client.get(f"/api/ideas/{idea_id}")).json()["todos"]
    assert len(todos) == 1
    assert todos[0]["id"] == todo["id"]
    assert todos[0]["github_issue_number"] == 21


@pytest.mark.asyncio
@respx.mock
async def test_deleting_a_todo_leaves_the_issue_open(users, make_client):
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _tracked_idea(client)
    todo = (
        await client.post(f"/api/ideas/{idea_id}/todos", json={"text": "tidy up"})
    ).json()
    respx.post(ISSUES).mock(
        return_value=httpx.Response(201, json=_issue(6, "tidy up"))
    )
    await client.post(f"/api/todos/{todo['id']}/issue")

    patch = respx.patch(f"{ISSUES}/6").mock(return_value=httpx.Response(200, json={}))
    assert (await client.delete(f"/api/todos/{todo['id']}")).status_code == 204
    assert not patch.called
