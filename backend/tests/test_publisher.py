"""Publishing a board into its repo.

The properties worth defending here are the ones that cost data or trust when
they break: an unchanged board must publish nothing, a moved tile must rewrite
one file, and nothing outside the board may ever be touched.
"""

import base64
import json

import httpx
import pytest
import respx

from app.boardrepo import MARKER_FILE
from app.ideafile import parse_idea_file
from app.publisher import blob_sha, diff, marker_content, publish_board
from app.rank import initial
from tests.conftest import client_as  # noqa: F401  (fixture helper)

BASE = "https://api.github.com"
REPO = "octocat/board"
REF = f"{BASE}/repos/{REPO}/git/ref/heads/main"


def _tree_url(sha: str) -> str:
    return f"{BASE}/repos/{REPO}/git/trees/{sha}"


class FakeRepo:
    """A board repo that remembers what was committed to it.

    Refuses git data writes while it has no commits, exactly as GitHub does
    ("Git Repository is empty"). That rule is the whole reason the publisher
    seeds through the contents API, so a fake without it would pass while the
    real thing failed.
    """

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        repo: str = REPO,
        *,
        initialised: bool = True,
    ):
        self.repo = repo
        self.files = dict(files or {})
        # GitHub initialises the repos this app creates, so a board normally
        # starts from a commit it did not make. initialised=False is the repo
        # somebody linked by hand before making one.
        self.head = "commit-0" if initialised else None
        self.commits = 0
        self.blobs: dict[str, bytes] = {}

    def tree(self) -> dict[str, str]:
        return {path: blob_sha(data) for path, data in self.files.items()}

    @property
    def empty(self) -> bool:
        return self.head is None

    def install(self, mock) -> None:
        base = f"{BASE}/repos/{self.repo}"
        mock.get(url__regex=rf"{base}/git/ref/heads/.*").mock(side_effect=self._ref)
        mock.get(url__regex=rf"{base}/git/trees/.*").mock(side_effect=self._get_tree)
        mock.post(f"{base}/git/blobs").mock(side_effect=self._blob)
        mock.post(f"{base}/git/trees").mock(side_effect=self._put_tree)
        mock.post(f"{base}/git/commits").mock(side_effect=self._commit)
        mock.patch(url__regex=rf"{base}/git/refs/heads/.*").mock(side_effect=self._update)

    def _empty_response(self) -> httpx.Response:
        return httpx.Response(409, json={"message": "Git Repository is empty."})

    def _ref(self, request):
        if self.head is None:
            return httpx.Response(409, json={"message": "Git Repository is empty."})
        return httpx.Response(200, json={"object": {"sha": self.head}})

    def _get_tree(self, request):
        if self.empty:
            return self._empty_response()
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"path": p, "type": "blob", "sha": s}
                    for p, s in self.tree().items()
                ],
            },
        )

    def _blob(self, request):
        if self.empty:
            return self._empty_response()
        data = base64.b64decode(json.loads(request.read())["content"])
        sha = blob_sha(data)
        self.blobs[sha] = data
        return httpx.Response(201, json={"sha": sha})

    def _put_tree(self, request):
        if self.empty:
            return self._empty_response()
        body = json.loads(request.read())
        if not body.get("base_tree"):
            self.files = {}
        for entry in body["tree"]:
            if entry["sha"] is None:
                self.files.pop(entry["path"], None)
            else:
                self.files[entry["path"]] = self.blobs[entry["sha"]]
        return httpx.Response(201, json={"sha": "tree-new"})

    def _commit(self, request):
        if self.empty:
            return self._empty_response()
        self.commits += 1
        return httpx.Response(201, json={"sha": f"commit-{self.commits}"})

    def _update(self, request):
        self.head = f"commit-{self.commits}"
        return httpx.Response(200, json={"object": {"sha": self.head}})


async def _board(session, user_id, titles, repo=REPO):
    """Give a user a board repo and some ideas."""
    from app.models import Idea, User

    user = await session.get(User, user_id)
    user.board_repo, user.board_branch = repo, "main"
    for pos, title in enumerate(titles):
        session.add(Idea(user_id=user_id, title=title, notes="", position=pos))
    await session.commit()
    return user


# ---- the pure parts ----


def test_blob_sha_matches_git():
    """Git's hash of an empty blob is a fixed, well-known value."""
    assert blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def test_diff_writes_only_what_changed():
    desired = {"a": b"one", "b": b"two"}
    current = {"a": blob_sha(b"one"), "b": blob_sha(b"different")}
    writes, removals = diff(desired, current)
    assert set(writes) == {"b"}
    assert removals == []


def test_diff_never_removes_anything_outside_the_board():
    """A board repo may hold a README, a licence, someone's actual project."""
    desired = {MARKER_FILE: b"{}"}
    current = {
        MARKER_FILE: blob_sha(b"{}"),
        "README.md": "whatever",
        "src/main.py": "whatever",
        "ideas/gone/IDEA.md": "whatever",
    }
    _writes, removals = diff(desired, current)
    assert removals == ["ideas/gone/IDEA.md"]


# ---- publishing ----


@pytest.mark.asyncio
@respx.mock
async def test_first_publish_writes_the_whole_board(users, make_client):
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["IdeaBRD", "Second"])
        result = await publish_board(s, user)

    assert result.committed and result.error is None
    assert repo.commits == 1, "a board is one commit, not one per file"
    assert set(repo.files) == {
        MARKER_FILE,
        "ideas/ideabrd/IDEA.md",
        "ideas/second/IDEA.md",
    }
    parsed = parse_idea_file(repo.files["ideas/ideabrd/IDEA.md"].decode())
    assert parsed.title == "IdeaBRD"
    assert parsed.rank is not None and parsed.color is not None


@pytest.mark.asyncio
@respx.mock
async def test_republishing_an_unchanged_board_commits_nothing(users, make_client):
    """The property that makes publishing cheap enough to do often."""
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["IdeaBRD", "Second"])
        await publish_board(s, user)
    async with SessionLocal() as s:
        from app.models import User

        again = await publish_board(s, await s.get(User, users["a"]))

    assert again.committed is False
    assert again.written == [] and again.removed == []
    assert repo.commits == 1


@pytest.mark.asyncio
@respx.mock
async def test_moving_one_tile_rewrites_one_file(users, make_client):
    """Fractional ranks earn their keep here or nowhere."""
    from app.db import SessionLocal
    from app.models import Idea, User

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["One", "Two", "Three", "Four"])
        await publish_board(s, user)

    async with SessionLocal() as s:
        # Send the last tile to the front, the way a drag on the board does:
        # by moving its position and nothing else.
        import sqlalchemy as sa

        ideas = (
            await s.execute(sa.select(Idea).order_by(Idea.position))
        ).scalars().all()
        ideas[-1].position = -1
        await s.commit()
        result = await publish_board(s, await s.get(User, users["a"]))

    assert result.committed
    assert result.written == ["ideas/four/IDEA.md"], result.written
    assert result.removed == []


@pytest.mark.asyncio
@respx.mock
async def test_a_tile_leaving_the_board_takes_its_directory(users, make_client):
    from app.db import SessionLocal
    from app.models import Idea, User

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["Keep", "Drop"])
        await publish_board(s, user)

    async with SessionLocal() as s:
        import sqlalchemy as sa

        idea = (
            await s.execute(sa.select(Idea).where(Idea.title == "Drop"))
        ).scalar_one()
        await s.delete(idea)
        await s.commit()
        result = await publish_board(s, await s.get(User, users["a"]))

    assert result.removed == ["ideas/drop/IDEA.md"]
    assert "ideas/drop/IDEA.md" not in repo.files
    assert "ideas/keep/IDEA.md" in repo.files


@pytest.mark.asyncio
@respx.mock
async def test_a_repo_that_is_not_a_board_is_not_written_to(users, make_client):
    """Same gate gitsync puts in front of seeding someone's repo."""
    from app.db import SessionLocal
    from app.models import User

    repo = FakeRepo({"README.md": b"my actual project\n"})
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["IdeaBRD"])
        result = await publish_board(s, user)

    assert result.needs_opt_in is True
    assert result.committed is False
    assert repo.commits == 0
    assert set(repo.files) == {"README.md"}

    async with SessionLocal() as s:
        opted = await publish_board(s, await s.get(User, users["a"]), opt_in=True)

    assert opted.committed
    assert repo.files["README.md"] == b"my actual project\n", "left someone's repo alone"
    assert "ideas/ideabrd/IDEA.md" in repo.files


@pytest.mark.asyncio
@respx.mock
async def test_slugs_are_stable_across_a_retitle(users, make_client):
    """A rename in git is a delete plus an add, so directories must not follow
    the title around."""
    from app.db import SessionLocal
    from app.models import Idea, User

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["Original Name"])
        await publish_board(s, user)

    async with SessionLocal() as s:
        import sqlalchemy as sa

        idea = (await s.execute(sa.select(Idea))).scalar_one()
        idea.title = "Something Else Entirely"
        await s.commit()
        await publish_board(s, await s.get(User, users["a"]))

    assert "ideas/original-name/IDEA.md" in repo.files
    assert "ideas/something-else-entirely/IDEA.md" not in repo.files
    parsed = parse_idea_file(repo.files["ideas/original-name/IDEA.md"].decode())
    assert parsed.title == "Something Else Entirely"


@pytest.mark.asyncio
@respx.mock
async def test_publish_reports_github_failure_without_raising(users, make_client):
    """A board is fine even when GitHub isn't; the caller gets a message."""
    from app.db import SessionLocal

    respx.get(REF).mock(return_value=httpx.Response(500, json={}))
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["IdeaBRD"])
        result = await publish_board(s, user)

    assert result.committed is False
    assert result.error is not None


@pytest.mark.asyncio
@respx.mock
async def test_a_shared_idea_gets_its_own_name_on_the_board(users, make_client):
    """Slugs are unique per owner, so two people can both have an "IdeaBRD".
    The board showing both has to name them apart."""
    from app.db import SessionLocal
    from app.models import Idea, IdeaCollaborator, User

    repo = FakeRepo()
    repo.install(respx.mock)
    async with SessionLocal() as s:
        await _board(s, users["a"], ["IdeaBRD"])
        # B's own idea, shared onto A's board under the same name.
        theirs = Idea(user_id=users["b"], title="IdeaBRD", notes="", position=0)
        s.add(theirs)
        await s.commit()
        s.add(
            IdeaCollaborator(
                idea_id=theirs.id, user_id=users["a"], role="editor", position=1
            )
        )
        await s.commit()
        result = await publish_board(s, await s.get(User, users["a"]))

    assert result.committed
    assert set(repo.files) == {
        MARKER_FILE,
        "ideas/ideabrd/IDEA.md",
        "ideas/ideabrd-2/IDEA.md",
    }
    # The collaborator's own row holds the board-local name, leaving the owner's
    # slug alone — the same idea keeps its own directory on their board.
    async with SessionLocal() as s:
        import sqlalchemy as sa

        member = (
            await s.execute(
                sa.select(IdeaCollaborator).where(IdeaCollaborator.user_id == users["a"])
            )
        ).scalar_one()
        owner_idea = await s.get(Idea, member.idea_id)
        assert member.slug == "ideabrd-2"
        assert owner_idea.slug is None, "publishing A's board must not name B's idea"


@pytest.mark.asyncio
@respx.mock
async def test_board_order_survives_a_round_trip(users, make_client):
    """Reading the published ranks back must reproduce the board's order."""
    from app.db import SessionLocal

    repo = FakeRepo()
    repo.install(respx.mock)
    titles = ["Alpha", "Bravo", "Charlie", "Delta"]
    async with SessionLocal() as s:
        user = await _board(s, users["a"], titles)
        await publish_board(s, user)

    by_rank = sorted(
        (
            (parse_idea_file(data.decode()).rank, parse_idea_file(data.decode()).title)
            for path, data in repo.files.items()
            if path.endswith("IDEA.md")
        )
    )
    assert [title for _rank, title in by_rank] == titles


@pytest.mark.asyncio
@respx.mock
async def test_a_repo_with_no_commits_is_refused_in_plain_words(users, make_client):
    """GitHub rejects every git data write to a repo with no commits — blobs
    included — so there is no first tree to build. Repos the app creates are
    initialised by GitHub; one linked by hand before its first commit lands
    here, and must say so rather than blaming a conflict."""
    from app.db import SessionLocal

    repo = FakeRepo(initialised=False)
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["IdeaBRD"])
        result = await publish_board(s, user)

    assert result.committed is False
    assert "no commits" in result.error
    assert repo.commits == 0


@pytest.mark.asyncio
@respx.mock
async def test_the_board_lands_in_one_commit_on_a_fresh_repo(users, make_client):
    """The initial commit is GitHub's; the board is a single commit on top."""
    from app.db import SessionLocal

    repo = FakeRepo({"README.md": b"# ideabrd-board\n"})
    repo.install(respx.mock)
    async with SessionLocal() as s:
        user = await _board(s, users["a"], ["IdeaBRD", "Second"])
        result = await publish_board(s, user, opt_in=True)

    assert result.committed and repo.commits == 1
    assert repo.files[MARKER_FILE] == marker_content()
    assert set(repo.files) == {
        "README.md",
        MARKER_FILE,
        "ideas/ideabrd/IDEA.md",
        "ideas/second/IDEA.md",
    }
