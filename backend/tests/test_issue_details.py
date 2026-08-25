"""Issue context on a tile: labels, assignee, comments, paging, and import.

A to-do backed by an issue used to mirror two fields and read one page. Both
were the kind of shortcut that looks harmless until a repo is real: a board
showed nothing about who owned an item, and issue #3 of a busy repo was pinned
to whatever state the to-do happened to be created with, because the first
hundred issues are the newest hundred.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from app.github import clear_cache, list_issues

BASE = "https://api.github.com"
REPO = "octocat/hello"
CONTENTS = f"{BASE}/repos/{REPO}/contents/IDEA.md"
ROOT = f"{BASE}/repos/{REPO}/contents/"
ISSUES = f"{BASE}/repos/{REPO}/issues"
PULLS = f"{BASE}/repos/{REPO}/pulls"


def _issue(number: int, **kw) -> dict:
    data = {
        "number": number,
        "title": kw.get("title", f"Issue {number}"),
        "state": kw.get("state", "open"),
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "labels": [{"name": n} for n in kw.get("labels", ())],
        "comments": kw.get("comments", 0),
    }
    if kw.get("assignee"):
        data["assignee"] = {"login": kw["assignee"]}
    return data


def _file(text: str, sha: str = "sha-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": base64.b64encode(text.encode()).decode(),
            "sha": sha,
            "type": "file",
        },
    )


def _mock_repo(idea_file: str = "# Repo idea", issues: list[dict] | None = None):
    """The calls a tile makes: IDEA.md, the root listing, the push, the issues."""
    respx.get(CONTENTS).mock(return_value=_file(idea_file))
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=[]))
    respx.get(ISSUES).mock(return_value=httpx.Response(200, json=issues or []))
    return respx.put(CONTENTS).mock(
        return_value=httpx.Response(200, json={"content": {"sha": "push-sha"}})
    )


async def _idea(client) -> int:
    resp = await client.post(
        "/api/ideas", json={"title": "Repo idea", "github_repo": REPO}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---- paging ----


@pytest.mark.asyncio
@respx.mock
async def test_issues_are_paged_past_the_first_hundred():
    pages = {
        "1": [_issue(n) for n in range(300, 200, -1)],
        "2": [_issue(n) for n in range(200, 150, -1)],
    }
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        seen.append(page)
        return httpx.Response(200, json=pages.get(page, []))

    respx.get(ISSUES).mock(side_effect=handler)
    issues = await list_issues(REPO)
    assert seen == ["1", "2"], "a short page ends the walk"
    assert 151 in issues and 300 in issues
    assert len(issues) == 150


@pytest.mark.asyncio
@respx.mock
async def test_pull_requests_are_never_mistaken_for_issues():
    respx.get(ISSUES).mock(
        return_value=httpx.Response(
            200,
            json=[_issue(2), {**_issue(1), "pull_request": {"url": "…"}}],
        )
    )
    assert set(await list_issues(REPO)) == {2}


# ---- what a tile shows ----


@pytest.mark.asyncio
@respx.mock
async def test_a_pull_brings_back_labels_assignee_and_comments(users, make_client):
    client = make_client(users["a"])
    _mock_repo(
        idea_file="# Repo idea\n\n## Todos\n\n- [ ] Build MVP (#12)\n",
        issues=[
            _issue(
                12,
                title="Build MVP",
                labels=["bug", "needs design"],
                assignee="octocat",
                comments=4,
            )
        ],
    )
    idea_id = await _idea(client)
    todo = (await client.get(f"/api/ideas/{idea_id}")).json()["todos"][0]
    assert todo["github_issue_labels"] == ["bug", "needs design"]
    assert todo["github_issue_assignee"] == "octocat"
    assert todo["github_issue_comments"] == 4


@pytest.mark.asyncio
@respx.mock
async def test_dropping_the_reference_drops_the_issue_context(users, make_client):
    """An item that is a plain to-do again must not keep another issue's labels."""
    client = make_client(users["a"])
    _mock_repo(
        idea_file="# Repo idea\n\n## Todos\n\n- [ ] Build MVP (#12)\n",
        issues=[_issue(12, title="Build MVP", labels=["bug"], assignee="octocat")],
    )
    idea_id = await _idea(client)
    assert (await client.get(f"/api/ideas/{idea_id}")).json()["todos"][0][
        "github_issue_labels"
    ] == ["bug"]

    # Someone takes "(#12)" out of the file by hand.
    respx.get(CONTENTS).mock(
        return_value=_file("# Repo idea\n\n## Todos\n\n- [ ] Build MVP\n", sha="sha-2")
    )
    todo = (await client.get(f"/api/ideas/{idea_id}")).json()["todos"][0]
    assert todo["github_issue_number"] is None
    assert todo["github_issue_labels"] is None
    assert todo["github_issue_assignee"] is None


# ---- import ----


@pytest.mark.asyncio
@respx.mock
async def test_import_adopts_a_repos_issues_as_todos(users, make_client):
    client = make_client(users["a"])
    _mock_repo(
        issues=[
            _issue(7, title="Older", labels=["chore"], comments=1),
            _issue(9, title="Newer", assignee="octocat"),
        ]
    )
    idea_id = await _idea(client)

    resp = await client.post(f"/api/ideas/{idea_id}/todos/import")
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert [(t["text"], t["github_issue_number"]) for t in body["todos"]] == [
        ("Older", 7),
        ("Newer", 9),
    ]
    assert body["todos"][0]["github_issue_labels"] == ["chore"]

    # Twice is a no-op, not a pile of duplicates.
    again = await client.post(f"/api/ideas/{idea_id}/todos/import")
    assert again.json()["imported"] == 0
    assert len(again.json()["todos"]) == 2


@pytest.mark.asyncio
@respx.mock
async def test_import_writes_the_imported_items_into_the_file(users, make_client):
    client = make_client(users["a"])
    put = _mock_repo(issues=[_issue(3, title="From GitHub")])
    idea_id = await _idea(client)
    await client.post(f"/api/ideas/{idea_id}/todos/import")
    pushed = base64.b64decode(
        json.loads(put.calls.last.request.read())["content"]
    ).decode()
    assert "- [ ] From GitHub (#3)" in pushed


@pytest.mark.asyncio
@respx.mock
async def test_import_needs_a_linked_repo(users, make_client):
    client = make_client(users["a"])
    resp = await client.post("/api/ideas", json={"title": "Note only"})
    idea_id = resp.json()["id"]
    resp = await client.post(f"/api/ideas/{idea_id}/todos/import")
    assert resp.status_code == 400


# ---- pull requests ----


@pytest.mark.asyncio
@respx.mock
async def test_open_pull_requests_are_listed_for_a_tile(users, make_client):
    clear_cache()
    client = make_client(users["a"])
    _mock_repo()
    idea_id = await _idea(client)
    respx.get(PULLS).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "number": 4,
                    "title": "Add the webhook",
                    "html_url": f"https://github.com/{REPO}/pull/4",
                    "user": {"login": "octocat"},
                    "draft": True,
                    "updated_at": "2026-08-24T10:00:00Z",
                }
            ],
        )
    )
    resp = await client.get(f"/api/ideas/{idea_id}/pulls")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "number": 4,
            "title": "Add the webhook",
            "html_url": f"https://github.com/{REPO}/pull/4",
            "author": "octocat",
            "draft": True,
            "updated_at": "2026-08-24T10:00:00Z",
        }
    ]


@pytest.mark.asyncio
@respx.mock
async def test_pulls_need_a_linked_repo(users, make_client):
    client = make_client(users["a"])
    idea_id = (await client.post("/api/ideas", json={"title": "Note only"})).json()["id"]
    assert (await client.get(f"/api/ideas/{idea_id}/pulls")).status_code == 404
