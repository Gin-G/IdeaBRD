"""Keeping the board repo level with the database, and proving that it is.

Three things that together decide whether git can be trusted with the board:

* **Dual-write** — every mutation reaches the repo on its own, so the git copy
  is what the board *is*, not what it was the last time somebody pressed a
  button.
* **Refusing to overwrite** — a repo that moved since our last publish is left
  alone, because a tree built on someone else's commit silently reverts it.
* **Reconciliation** — a read-only diff of both copies, which is the evidence
  the cutover decision is supposed to rest on.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app import dualwrite
from app.boardrepo import MARKER_FILE
from app.publisher import publish_board
from app.reconcile import (
    DIFFERS,
    MISSING_IN_BOARD,
    MISSING_IN_REPO,
    SAME,
    reconcile_board,
)
from tests.test_publisher import FakeRepo, _board


@pytest.fixture(autouse=True)
def instant_dual_write(monkeypatch):
    """No debounce in tests; the coalescing is exercised on its own below."""
    monkeypatch.setattr(dualwrite, "DEBOUNCE_SECONDS", 0)
    dualwrite.reset()
    yield
    dualwrite.reset()


async def _publish_first(session, user):
    """Publish once so the repo starts out matching the board."""
    result = await publish_board(session, user)
    assert result.committed or result.error is None
    return result


# ---- dual-write ----


@pytest.mark.asyncio
@respx.mock
async def test_creating_an_idea_reaches_the_repo_without_being_asked(
    users, make_client
):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        await _board(s, users["a"], [])

    client = make_client(users["a"])
    resp = await client.post("/api/ideas", json={"title": "Written in git"})
    assert resp.status_code == 201
    await dualwrite.drain()

    assert "ideas/written-in-git/IDEA.md" in repo.files
    assert MARKER_FILE in repo.files


@pytest.mark.asyncio
@respx.mock
async def test_a_burst_of_edits_is_one_commit(users, make_client, monkeypatch):
    """Dragging a tile is a dozen mutations; it should not be a dozen commits."""
    from app.db import SessionLocal

    # The window has to outlast the burst, or the thing being tested cannot
    # happen: four requests through the app take longer than 50ms on a loaded
    # CI runner, and the worker then publishes partway through and commits
    # more than once. A second is far more than the burst needs and still
    # far less than the real 2s default.
    monkeypatch.setattr(dualwrite, "DEBOUNCE_SECONDS", 1.0)
    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)
    commits_before = repo.commits

    client = make_client(users["a"])
    idea_id = (await client.get("/api/ideas")).json()[0]["id"]
    for progress in (10, 20, 30, 40):
        await client.patch(f"/api/ideas/{idea_id}", json={"progress": progress})
    await dualwrite.drain()

    assert repo.commits - commits_before == 1
    assert b"progress: 40" in repo.files["ideas/one/IDEA.md"]


@pytest.mark.asyncio
@respx.mock
async def test_a_board_with_no_repo_schedules_nothing(users, make_client):
    """Most boards have no repo; they must not pay for this at all."""
    client = make_client(users["a"])
    assert (await client.post("/api/ideas", json={"title": "Local only"})).status_code == 201
    await dualwrite.drain()
    assert not respx.calls, "no repo means no GitHub traffic"


@pytest.mark.asyncio
@respx.mock
async def test_a_shared_idea_is_written_to_every_board_that_shows_it(
    users, make_client
):
    from app.db import SessionLocal
    from app.models import Idea, IdeaCollaborator, User

    mine = FakeRepo(repo="octocat/board")
    theirs = FakeRepo(repo="octocat/other-board")
    mine.install(respx.mock)
    theirs.install(respx.mock)

    async with SessionLocal() as s:
        owner = await _board(s, users["a"], ["Shared idea"])
        friend = await s.get(User, users["b"])
        friend.board_repo, friend.board_branch = "octocat/other-board", "main"
        idea = (await s.execute(Idea.__table__.select())).first()
        s.add(
            IdeaCollaborator(idea_id=idea.id, user_id=friend.id, role="editor", position=0)
        )
        await s.commit()
        await _publish_first(s, owner)

    client = make_client(users["a"])
    idea_id = (await client.get("/api/ideas")).json()[0]["id"]
    await client.patch(f"/api/ideas/{idea_id}", json={"status": "done"})
    await dualwrite.drain()

    assert b"status: done" in mine.files["ideas/shared-idea/IDEA.md"]
    assert b"status: done" in theirs.files["ideas/shared-idea/IDEA.md"]


@pytest.mark.asyncio
@respx.mock
async def test_a_failed_dual_write_is_recorded_rather_than_lost(users, make_client):
    from app.db import SessionLocal

    async with SessionLocal() as s:
        await _board(s, users["a"], [])
    # GitHub is unreachable for the duration.
    respx.get(url__regex=r".*").mock(side_effect=httpx.ConnectError("no network"))

    client = make_client(users["a"])
    await client.post("/api/ideas", json={"title": "Doomed"})
    await dualwrite.drain()

    state = dualwrite.state_for(users["a"])
    assert state.last_error, "a dual-write that stopped working has to say so"
    assert (await client.get("/api/board")).json()["sync"]["last_error"]


# ---- refusing to publish over a moved repo ----


@pytest.mark.asyncio
@respx.mock
async def test_a_repo_that_moved_is_not_published_over(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)

        # Somebody commits to the board repo directly.
        repo.files["ideas/one/IDEA.md"] = b"---\nstatus: done\n---\n\n# Edited by hand\n"
        repo.head = "commit-by-hand"

        result = await publish_board(s, user)
        assert result.moved is True
        assert result.committed is False
        assert result.head_sha == "commit-by-hand"
        assert repo.files["ideas/one/IDEA.md"].startswith(b"---\nstatus: done")


@pytest.mark.asyncio
@respx.mock
async def test_force_publishes_over_a_moved_repo(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)
        repo.files["ideas/one/IDEA.md"] = b"# Edited by hand\n"
        repo.head = "commit-by-hand"

        result = await publish_board(s, user, force=True)
        assert result.committed is True
        assert b"# One" in repo.files["ideas/one/IDEA.md"]


@pytest.mark.asyncio
@respx.mock
async def test_a_dry_run_reports_the_move_and_still_diffs(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)
        repo.files["ideas/one/IDEA.md"] = b"# Edited by hand\n"
        repo.head = "commit-by-hand"

        result = await publish_board(s, user, dry_run=True)
        assert result.moved is True
        assert result.written == ["ideas/one/IDEA.md"]
        assert repo.commits == 1, "a dry run commits nothing"


# ---- reconciliation ----


@pytest.mark.asyncio
@respx.mock
async def test_a_published_board_reconciles_clean(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One", "Two"])
        await _publish_first(s, user)
        report = await reconcile_board(s, user)

    assert report.in_sync is True
    assert {e.slug for e in report.entries} == {"one", "two"}
    assert all(e.state == SAME for e in report.entries)


@pytest.mark.asyncio
@respx.mock
async def test_reconcile_names_the_fields_that_differ(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)
        repo.files["ideas/one/IDEA.md"] = (
            b'---\nstatus: done\nprogress: 10\ncolor: "#6366f1"\nrank: "i"\n---\n\n'
            b"# One\n\n## Todos\n\n- [ ] added by hand\n"
        )

        report = await reconcile_board(s, user)

    assert report.in_sync is False
    entry = report.entries[0]
    assert entry.state == DIFFERS
    assert set(entry.differences) == {"status", "progress", "todos"}


@pytest.mark.asyncio
@respx.mock
async def test_reconcile_reports_both_kinds_of_missing(users, make_client):
    from app.db import SessionLocal
    from app.models import Idea

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)

        # An idea the repo has never heard of...
        s.add(Idea(user_id=user.id, title="Unpublished", notes="", position=9))
        await s.commit()
        # ...and a directory the board doesn't have.
        repo.files["ideas/ghost/IDEA.md"] = b"# Ghost\n"

        report = await reconcile_board(s, user)

    states = {e.slug: e.state for e in report.entries}
    assert states["unpublished"] == MISSING_IN_REPO
    assert states["ghost"] == MISSING_IN_BOARD
    assert report.in_sync is False


@pytest.mark.asyncio
@respx.mock
async def test_reconcile_is_read_only(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One"])
        await _publish_first(s, user)
        commits = repo.commits
        await reconcile_board(s, user)
        assert repo.commits == commits


@pytest.mark.asyncio
@respx.mock
async def test_reconcile_endpoint_needs_a_board_repo(users, make_client):
    client = make_client(users["a"])
    assert (await client.get("/api/board/reconcile")).status_code == 400
