"""The public page: a board owner's flagged ideas, read from git, shown to anyone.

Most of what is tested here is what must NOT leave: unflagged tiles, notes past
the first paragraph, to-do text, and the names of private repos. The page reads
private repos with the owner's token on behalf of anonymous visitors, so every
one of those is a leak if it regresses.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from app import store
from app.ideafile import normalize_site, parse_idea_file, render_idea_file, render_reference_file
from app.ideamerge import merge_idea_files
from app.models import Idea, IdeaCollaborator, Identity
from app.publisher import BoardTile, render_tile
from app.routers import public
from app.routers.public import summarize
from tests.test_publisher import BASE, REPO, FakeRepo

# --------------------------------------------------------------------------
# The flag in the file


def test_public_is_off_unless_the_file_says_so():
    assert parse_idea_file("---\nstatus: idea\n---\n\n# A\n").public is False
    assert parse_idea_file("---\npublic: true\n---\n\n# A\n").public is True
    assert parse_idea_file("---\npublic: yes\n---\n\n# A\n").public is True
    # A typo costs the flag, never publishes the tile.
    assert parse_idea_file("---\npublic: ture\n---\n\n# A\n").public is False


def test_a_private_idea_renders_exactly_as_it_did_before_the_flag():
    kwargs = dict(title="A", notes="n", status="idea", progress=0, todos=[], rank="m")

    def frontmatter(text: str) -> str:
        return text.split("---")[1]

    assert "public" not in frontmatter(render_idea_file(**kwargs))
    assert "public: true" in frontmatter(render_idea_file(**kwargs, public=True))
    assert "public" not in render_reference_file(repo="o/r", rank="m", color="#123456")


def test_the_flag_survives_a_round_trip_and_a_merge():
    stub = render_reference_file(repo="o/r", rank="m", color="#123456", public=True)
    assert parse_idea_file(stub).public is True
    # The other side only moved the tile; the flag must not be lost doing it.
    moved = stub.replace('rank: "m"', 'rank: "q"')
    merged, parsed = merge_idea_files(stub, moved, stub, guidance=False)
    assert parsed.public is True and parsed.rank == "q"
    assert "public: true" in merged


def _idea(**kw) -> Idea:
    base = dict(
        title="Thing", notes="", status="idea", progress=0, color="#6366f1",
        github_repo=None, public=False,
    )
    idea = Idea(**{**base, **kw})
    idea.todos = []
    return idea


def test_the_publisher_writes_the_flag_on_the_owners_own_tiles_only():
    owned = BoardTile(idea=_idea(public=True), slug="thing", rank="m")
    assert parse_idea_file(render_tile(owned)).public is True

    linked = BoardTile(idea=_idea(public=True, github_repo="o/r"), slug="thing", rank="m")
    assert parse_idea_file(render_tile(linked)).public is True

    shared = BoardTile(
        idea=_idea(public=True), slug="thing", rank="m", membership=IdeaCollaborator()
    )
    assert parse_idea_file(render_tile(shared)).public is False


# --------------------------------------------------------------------------
# What the page shows


def test_the_summary_is_the_first_paragraph_as_plain_text():
    notes = (
        "**Bold** pitch with a [link](https://x.example) and `code`.\n"
        "Same paragraph.\n\nSecrets live in OpenBao at hench/plaid."
    )
    assert summarize(notes) == "Bold pitch with a link and code. Same paragraph."


def test_a_site_is_a_web_address_with_https_assumed():
    assert normalize_site("hydrow.example.net") == "https://hydrow.example.net"
    assert normalize_site("http://x.example/app") == "http://x.example/app"
    assert normalize_site("  ") is None
    assert normalize_site("not a site") is None
    assert normalize_site("javascript:alert(1)") is None


def test_site_keys_round_trip_and_stay_out_of_files_without_them():
    plain = render_idea_file(title="A", notes="", status="idea", progress=0, todos=[])
    assert "site" not in plain.split("---")[1]

    shown = render_idea_file(
        title="A", notes="", status="idea", progress=0, todos=[],
        site="https://a.example", site_public=True,
    )
    parsed = parse_idea_file(shown)
    assert (parsed.site, parsed.site_public) == ("https://a.example", True)

    hidden = parse_idea_file("---\nsite: a.example\n---\n\n# A\n")
    assert (hidden.site, hidden.site_public) == ("https://a.example", False)
    # site_public means nothing without a site.
    assert parse_idea_file("---\nsite_public: true\n---\n\n# A\n").site_public is False


def test_the_guidance_explains_the_public_page():
    from app.ideafile import GUIDANCE
    assert "site_public" in GUIDANCE and "FIRST PARAGRAPH" in GUIDANCE


# --------------------------------------------------------------------------
# The endpoint

OWNER = "octocat"


def _b64(text: str) -> dict:
    return {"content": base64.b64encode(text.encode()).decode(), "sha": "s"}


def _board_file(
    title: str, notes: str, *, rank: str, public: bool,
    site: str | None = None, site_public: bool = False,
) -> bytes:
    return render_idea_file(
        title=title, notes=notes, status="active", progress=40,
        todos=[("done one", True), ("open one", False)],
        rank=rank, public=public, guidance=False, site=site, site_public=site_public,
    ).encode()


@pytest.fixture(autouse=True)
def _fresh():
    store.clear_cache()
    public.clear_cache()
    yield
    store.clear_cache()
    public.clear_cache()


@pytest.fixture
async def owner(users):
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as s:
        user = await s.get(User, users["a"])
        user.board_repo = REPO
        s.add(Identity(
            user_id=user.id, provider="github", subject="1",
            github_login="OctoCat", github_token="tok",
        ))
        await s.commit()
    return users["a"]


def _install(mock):
    FakeRepo({
        ".ideabrd": b"",
        "ideas/shown/IDEA.md": _board_file(
            "Shown", "The pitch, live at https://notes-link.example.\n\nInternal detail.",
            rank="c", public=True, site="shown.example", site_public=True,
        ),
        "ideas/shown/idea_logo.png": b"\x89PNG",
        "ideas/hidden/IDEA.md": _board_file("Hidden", "Not for you.", rank="d", public=False),
        "ideas/secret-repo/IDEA.md": render_reference_file(
            repo="octocat/secret-thing", rank="e", color="#123456", public=True
        ).encode(),
        "ideas/oss/IDEA.md": render_reference_file(
            repo="octocat/oss", rank="f", color="#123456", public=True
        ).encode(),
    }).install(mock)

    linked = render_idea_file(
        title="Linked", notes="Linked pitch.\n\nLinked internals.", status="done",
        progress=100, todos=[("a", True)], site="behind-login.example",
    )
    for name, private in (("secret-thing", True), ("oss", False)):
        base = f"{BASE}/repos/octocat/{name}"
        mock.get(f"{base}/contents/IDEA.md").mock(
            return_value=httpx.Response(200, json=_b64(linked))
        )
        mock.get(base).mock(return_value=httpx.Response(200, json={
            "full_name": f"octocat/{name}",
            "html_url": f"https://github.com/octocat/{name}",
            "private": private,
        }))


@pytest.mark.asyncio
@respx.mock
async def test_the_page_shows_flagged_ideas_and_nothing_else(owner, anon_client):
    _install(respx.mock)

    r = await anon_client.get("/api/public/octocat")  # login is case-insensitive

    assert r.status_code == 200
    body = r.json()
    assert body["login"] == "OctoCat"
    by_slug = {i["slug"]: i for i in body["ideas"]}
    assert list(by_slug) == ["shown", "secret-repo", "oss"]  # board order, no "hidden"

    shown = by_slug["shown"]
    assert shown["summary"] == "The pitch, live at https://notes-link.example."
    assert shown["site_url"] == "https://shown.example"  # the field, not the notes
    assert (shown["todos_done"], shown["todos_total"]) == (1, 2)
    assert shown["logo_url"] == "/api/public/OctoCat/logo/shown"

    assert by_slug["oss"]["repo_url"] == "https://github.com/octocat/oss"
    assert by_slug["oss"]["site_url"] is None  # has a site, not marked public
    assert by_slug["oss"]["status"] == "done"
    assert by_slug["secret-repo"]["repo_url"] is None

    raw = json.dumps(body)
    for leak in ("Internal detail", "Linked internals", "Not for you", "open one",
                 "secret-thing", "tok", "behind-login"):
        assert leak not in raw, leak


@pytest.mark.asyncio
@respx.mock
async def test_no_owner_and_no_board_look_the_same(owner, anon_client, users):
    assert (await anon_client.get("/api/public/nobody")).status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_a_logo_is_served_only_for_a_public_tile(owner, anon_client):
    _install(respx.mock)

    ok = await anon_client.get("/api/public/octocat/logo/shown")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert (await anon_client.get("/api/public/octocat/logo/hidden")).status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_a_page_is_built_once_per_cache_window(owner, anon_client):
    _install(respx.mock)
    await anon_client.get("/api/public/octocat")
    calls = respx.mock.calls.call_count

    await anon_client.get("/api/public/octocat")

    assert respx.mock.calls.call_count == calls


@pytest.mark.asyncio
async def test_the_owner_can_toggle_the_flag_through_the_api(users, make_client):
    async with make_client(users["a"]) as c:
        made = (await c.post("/api/ideas", json={"title": "Show me"})).json()
        assert made["public"] is False

        r = await c.patch(f"/api/ideas/{made['id']}", json={"public": True})
        assert r.status_code == 200 and r.json()["public"] is True

        board = (await c.get("/api/ideas")).json()
        assert next(i for i in board if i["id"] == made["id"])["public"] is True

        r = await c.patch(f"/api/ideas/{made['id']}",
                          json={"site": "thing.example", "site_public": True})
        assert (r.json()["site"], r.json()["site_public"]) == ("https://thing.example", True)

        bad = await c.patch(f"/api/ideas/{made['id']}", json={"site": "not a site"})
        assert bad.status_code == 422
