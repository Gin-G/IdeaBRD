import base64
import json

import httpx
import pytest
import respx

from app.ideafile import parse_idea_file, render_idea_file

BASE = "https://api.github.com"
CONTENTS = f"{BASE}/repos/octocat/hello/contents/IDEA.md"
# Every pull also lists the repo root, looking for a tile logo (see test_logo_sync).
ROOT = f"{BASE}/repos/octocat/hello/contents/"


def _no_repo_logo() -> None:
    respx.get(ROOT).mock(return_value=httpx.Response(200, json=[]))


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
    assert parsed.todos == [("set up repo", True, None), ("build MVP", False, None)]


def test_rendered_file_documents_its_own_format():
    """A seeded file has to teach its own rules — it's all the next editor sees.

    The two things that silently cost a whole list: guessing the heading name,
    and not knowing the section exists at all. Beyond the format, the file also
    has to say what it is *for*: an agent handed the repo will otherwise track
    its work in a TODO.md or a plan nobody on the board can see.
    """
    text = render_idea_file(
        title="Fresh", notes="", status="idea", progress=0, todos=[]
    )
    assert "## Todos" in text  # present even with nothing in it
    assert "<!--" in text and "-->" in text
    for rule in ("## ToDo", "exact text", "one line", "the board", "(#12)"):
        assert rule in text
    for instruction in ("This file is the to-do list", "TODO.md", "open a real issue"):
        assert instruction in text

    # ...and none of it leaks onto the board or into the list.
    parsed = parse_idea_file(text)
    assert parsed.title == "Fresh"
    assert parsed.notes == ""
    assert parsed.todos == []
    # Re-rendering what we parsed reproduces the file, so guidance doesn't
    # accumulate or churn the sha across pull/push cycles.
    assert (
        render_idea_file(
            title=parsed.title,
            notes=parsed.notes,
            status="idea",
            progress=0,
            todos=parsed.todos,
        )
        == text
    )


def test_comments_are_stripped_not_stored():
    """Comments must vanish wherever they sit — including "- [ ]" inside them."""
    parsed = parse_idea_file(
        "# T\n\n<!-- multi\nline\n- [ ] not a real todo\n-->\n\nreal notes\n"
        "<!-- inline -->\n\n## Todos\n\n<!-- ignore me -->\n- [x] real\n"
    )
    assert parsed.notes == "real notes"
    assert parsed.todos == [("real", True, None)]


def test_parse_lenient():
    # No frontmatter, no title, stray text in the todos section, later section.
    parsed = parse_idea_file(
        "just some notes\n\n## To-Dos\nnot an item\n- [X] shipped\n* [ ] next\n\n## Links\nmore"
    )
    assert parsed.title is None
    assert parsed.status is None
    assert parsed.progress is None
    assert parsed.todos == [("shipped", True, None), ("next", False, None)]
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
    _no_repo_logo()
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
    _no_repo_logo()
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
    # The seeded file is the whole spec for whoever edits it next.
    assert "## Todos" in content
    assert "<!--" in content
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
async def test_pull_untracks_a_deleted_idea_file(users, make_client):
    """Deleting IDEA.md in the repo puts the idea back in the untracked state.

    Tracking is read off the stored sha, so a sha left behind by the last good
    pull keeps the page claiming the file is still there — and keeps app edits
    pushing, which commits the file the user deleted straight back.
    """
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    respx.get(CONTENTS).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    put_route = respx.put(CONTENTS).mock(
        return_value=httpx.Response(200, json={"content": {"sha": "recreated-sha"}})
    )
    # Re-mocking a pattern returns the same respx route, so the seed commit is
    # still on its ledger — count pushes from here rather than asserting called.
    seeded = put_route.call_count

    resp = await client.get(f"/api/ideas/{idea_id}")
    assert resp.status_code == 200
    assert resp.json()["git_file_missing"] is True
    assert resp.json()["git_synced_at"] is None

    # ...so an app edit keeps to itself instead of recreating the file.
    resp = await client.patch(f"/api/ideas/{idea_id}", json={"notes": "local again"})
    assert resp.status_code == 200
    assert resp.json()["git_file_missing"] is True
    assert put_route.call_count == seeded

    # Putting it back is the same explicit opt-in as the first time.
    resp = await client.post(f"/api/ideas/{idea_id}/sync?init=true")
    assert resp.status_code == 200
    assert resp.json()["git_file_missing"] is False
    assert put_route.call_count == seeded + 1
    assert "local again" in _pushed_content(put_route.calls.last.request)


@pytest.mark.asyncio
@respx.mock
async def test_pull_drops_todos_removed_from_the_file(users, make_client):
    """To-dos deleted or reworded in IDEA.md must not linger on the board.

    Matching is by exact text, so a reworded item is a delete plus an insert —
    if the delete is skipped the old row survives as a duplicate.
    """
    client = make_client(users["a"])
    idea_id = await _create_tracked_idea(client, respx)

    head = "---\nstatus: active\nprogress: 10\n---\n\n# Repo idea\n\n## Todos\n\n"
    respx.get(CONTENTS).mock(
        return_value=_file_response(
            head + "- [x] keep me\n- [ ] rename me\n- [ ] drop me\n", sha="sha-2"
        )
    )
    resp = await client.get(f"/api/ideas/{idea_id}")
    assert [t["text"] for t in resp.json()["todos"]] == [
        "keep me",
        "rename me",
        "drop me",
    ]

    respx.get(CONTENTS).mock(
        return_value=_file_response(head + "- [x] keep me\n- [ ] renamed\n", sha="sha-3")
    )
    resp = await client.get(f"/api/ideas/{idea_id}")
    assert [(t["text"], t["done"]) for t in resp.json()["todos"]] == [
        ("keep me", True),
        ("renamed", False),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_get_adopts_existing_idea_file(users, make_client):
    """Linking a repo that already has an IDEA.md adopts it without prompting."""
    client = make_client(users["a"])
    respx.get(CONTENTS).mock(
        return_value=_file_response("# From the repo\n\nrepo notes", sha="repo-sha")
    )
    _no_repo_logo()
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
