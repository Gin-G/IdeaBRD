"""The board read straight from its repository, with no database involved.

This is the store the API moves onto as the database goes away, so what
matters here is that a repo is enough on its own: the ideas, their order,
their logos, and ids that the browser and the phone arrive at independently.
"""

from __future__ import annotations

import pytest
import respx

from app import store
from app.store import id_for, read_board, read_idea
from tests.test_publisher import REPO, FakeRepo


def idea(title: str, *, rank: str, status: str = "active", progress: int = 0) -> bytes:
    return (
        f"---\nstatus: {status}\nprogress: {progress}\nrank: \"{rank}\"\n---\n\n"
        f"# {title}\n\nNotes for {title}.\n\n## Todos\n\n- [ ] something\n"
    ).encode()


@pytest.fixture
def board_repo():
    return FakeRepo(
        {
            ".ideabrd": b"",
            "ideas/second/IDEA.md": idea("Second", rank="m"),
            "ideas/first/IDEA.md": idea("First", rank="c", progress=40),
            "ideas/first/idea_logo.png": b"\x89PNG-not-really",
        }
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    store.clear_cache()
    yield
    store.clear_cache()


@pytest.mark.asyncio
@respx.mock
async def test_a_repo_is_the_whole_board(board_repo):
    board_repo.install(respx.mock)

    board = await read_board(REPO, token="t")

    assert [t.slug for t in board.tiles] == ["first", "second"]  # by rank, not name
    first = board.by_slug("first")
    assert first.file.title == "First"
    assert first.file.progress == 40
    assert "Notes for First." in (first.file.notes or "")
    assert [t.text for t in first.file.todos] == ["something"]


@pytest.mark.asyncio
@respx.mock
async def test_a_logo_beside_an_idea_belongs_to_it(board_repo):
    board_repo.install(respx.mock)

    board = await read_board(REPO, token="t")

    assert board.by_slug("first").logo_path == "ideas/first/idea_logo.png"
    assert board.by_slug("second").logo_path is None


@pytest.mark.asyncio
@respx.mock
async def test_an_idea_is_found_by_the_id_the_browser_would_use(board_repo):
    board_repo.install(respx.mock)

    board = await read_board(REPO, token="t")

    assert board.by_id(id_for("first")).slug == "first"
    assert board.by_id(id_for("nothing-here")) is None


@pytest.mark.asyncio
@respx.mock
async def test_a_second_read_of_the_same_commit_costs_one_request(board_repo):
    """Listing is a tree and a blob per idea; polling must not repeat that."""
    board_repo.install(respx.mock)

    await read_board(REPO, token="t")
    before = respx.mock.calls.call_count
    await read_board(REPO, token="t")
    after = respx.mock.calls.call_count

    # Exactly one: the ref, to find out whether anything moved.
    assert after - before == 1


@pytest.mark.asyncio
@respx.mock
async def test_a_new_commit_is_read_again(board_repo):
    board_repo.install(respx.mock)
    await read_board(REPO, token="t")

    board_repo.files["ideas/third/IDEA.md"] = idea("Third", rank="z")
    board_repo.head = "commit-1"

    board = await read_board(REPO, token="t")
    assert [t.slug for t in board.tiles] == ["first", "second", "third"]


@pytest.mark.asyncio
@respx.mock
async def test_a_repo_with_no_commits_is_an_empty_board():
    """What a board looks like in the moment after it is created."""
    FakeRepo({}, initialised=False).install(respx.mock)

    board = await read_board(REPO, token="t")

    assert board.commit is None
    assert board.tiles == []


@pytest.mark.asyncio
@respx.mock
async def test_reading_one_idea(board_repo):
    board_repo.install(respx.mock)

    assert (await read_idea(REPO, "second", token="t")).file.title == "Second"
    assert await read_idea(REPO, "absent", token="t") is None


def test_ids_match_the_browser_and_the_phone():
    """Hard-coded from the TypeScript `idFor`, which is the one in the APK too.

    A board opened in a browser and the same board opened on a phone have to
    agree on what /api/ideas/759392415 means.
    """
    assert id_for("ideabrd") == 759392415
    assert id_for("trout-temps") == 312145875
    assert id_for("a") == 1913001110
    assert id_for("") == 1083068130
