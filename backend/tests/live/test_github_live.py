"""The GitHub client, against GitHub.

Every other test here mocks the API, and mocks agree with whatever the code
believes. That is exactly how the board publisher shipped with a green suite
and could not make its first commit: GitHub rejects *all* git data writes to a
repo with no commits, and no mock had ever said so.

So this suite talks to the real thing. It creates a throwaway repository, puts
a board in it, reads it back through a different API than it was written with,
and deletes the repo at the end. It is skipped unless a token is provided,
because a test that needs credentials must never be the reason a pull request
goes red for someone who does not have them.

Run it with:

    IDEABRD_GITHUB_TOKEN=ghp_… pytest tests/live -m live

The token needs ``repo`` and ``delete_repo``. Use a throwaway account or an
organisation you don't mind having a repo appear in for thirty seconds.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from app.github import (
    create_issue,
    delete_file,
    delete_repo,
    get_file,
    get_tree,
    list_issues,
    list_pulls,
    put_file,
    update_issue,
)
from app.publisher import publish_board
from app.reconcile import reconcile_board

TOKEN = os.environ.get("IDEABRD_GITHUB_TOKEN", "")
ORG = os.environ.get("IDEABRD_GITHUB_ORG") or None

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not TOKEN, reason="IDEABRD_GITHUB_TOKEN is not set"),
]


async def _eventually(call, *, until, what, attempts=10, delay=1.0):
    """Retry until GitHub agrees with itself.

    Creating an issue and listing issues are not read-your-writes consistent:
    the create returns #1 and the list is still empty a moment later. That is
    GitHub's behaviour, not a bug in the client — the same call a few seconds
    on returns it — so the suite waits rather than reporting a failure that
    says nothing about this code.
    """
    last = None
    for _ in range(attempts):
        last = await call()
        if until(last):
            return last
        await asyncio.sleep(delay)
    raise AssertionError(f"Gave up waiting for {what}; last saw {last!r}")


@pytest.fixture
async def throwaway_repo():
    """A real repository, created for one test and deleted afterwards."""
    from app.github import create_repo

    name = f"ideabrd-live-{int(time.time())}"
    full_name, branch = await create_repo(
        name,
        org=ORG,
        private=True,
        description="IdeaBRD live test — safe to delete",
        token=TOKEN,
    )
    try:
        yield full_name, branch
    finally:
        # Deleting needs `delete_repo`, which a token with plain `repo` does
        # not have. That is a reason to leave a repository behind and say so,
        # not a reason to fail a suite that has already done its job.
        try:
            await delete_repo(full_name, token=TOKEN)
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            print(
                f"\nCould not delete {full_name}: {exc}\n"
                f"Delete it by hand, or give the token the `delete_repo` scope.",
            )


@pytest.mark.asyncio
async def test_a_board_publishes_into_a_fresh_repo(users, throwaway_repo):
    """The whole publish path, on a repo GitHub only just made."""
    from app.db import SessionLocal
    from app.models import Idea, Identity, User

    full_name, branch = throwaway_repo
    async with SessionLocal() as session:
        user = await session.get(User, users["a"])
        user.board_repo, user.board_branch = full_name, branch
        session.add(
            Identity(
                user_id=user.id,
                provider="github",
                subject="live",
                github_token=TOKEN,
            )
        )
        session.add(Idea(user_id=user.id, title="Live one", notes="first", position=0))
        session.add(Idea(user_id=user.id, title="Live two", notes="second", position=1))
        await session.commit()

        result = await publish_board(session, user, opt_in=True)
        assert result.error is None, result.error
        assert result.committed is True

        # Read it back through the trees API rather than trusting the writer.
        tree = await get_tree(full_name, result.commit_sha, token=TOKEN)
        assert "ideas/live-one/IDEA.md" in tree
        assert "ideas/live-two/IDEA.md" in tree
        assert ".ideabrd" in tree

        found = await get_file(full_name, "ideas/live-one/IDEA.md", token=TOKEN)
        assert found is not None and "# Live one" in found[0]

        # An unchanged board publishes nothing at all.
        again = await publish_board(session, user)
        assert again.committed is False and again.error is None

        report = await reconcile_board(session, user)
        assert report.in_sync is True, [vars(e) for e in report.entries]


@pytest.mark.asyncio
async def test_contents_and_issues_round_trip(throwaway_repo):
    full_name, _branch = throwaway_repo

    sha = await put_file(
        full_name, "IDEA.md", "# Live\n\n## Todos\n", "add idea file", token=TOKEN
    )
    found = await get_file(full_name, "IDEA.md", token=TOKEN)
    assert found is not None and found[1] == sha

    issue = await create_issue(full_name, "Live issue", "body", token=TOKEN)
    assert issue.number > 0
    listed = await _eventually(
        lambda: list_issues(full_name, token=TOKEN),
        until=lambda found: issue.number in found,
        what=f"issue #{issue.number} to appear in the list",
    )
    assert listed[issue.number].title == "Live issue"

    closed = await update_issue(full_name, issue.number, state="closed", token=TOKEN)
    assert closed.state == "closed"

    assert await list_pulls(full_name, token=TOKEN) == []

    await delete_file(full_name, "IDEA.md", "remove idea file", sha=sha, token=TOKEN)
    assert await get_file(full_name, "IDEA.md", token=TOKEN) is None
