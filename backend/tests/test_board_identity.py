"""The board repo's two identities: what names an idea, and what orders it.

Both exist because the git-only board has no manifest. Order lives in each
idea's own file, so the property worth defending is that moving one tile
rewrites one file — not that the ranks are pretty.
"""

import pytest

from app.boardrepo import idea_file_path, is_slug, slugify, unique_slug
from app.ideafile import parse_idea_file, render_idea_file
from app.rank import InvalidRank, between, initial, is_rank, repair


def test_between_always_finds_room():
    assert between(None, None) == "i"
    assert between("i", None) > "i"
    assert "i" < between("i", "r") < "r"
    # Adjacent digits leave no gap, so the key grows instead of failing.
    assert "a" < between("a", "b") < "b"


def test_between_rejects_bounds_it_cannot_honour():
    """A stale pair must fail loudly rather than sort somewhere unexpected."""
    with pytest.raises(InvalidRank):
        between("r", "i")
    with pytest.raises(InvalidRank):
        between("i", "i")
    with pytest.raises(InvalidRank):
        between("not a rank!", None)


def test_repeated_inserts_into_one_slot_stay_bounded():
    keys = ["a", "b"]
    for _ in range(50):
        keys.insert(1, between(keys[0], keys[1]))
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    assert max(len(k) for k in keys) < 20


def test_repair_leaves_a_settled_board_alone():
    """The no-op case is the one that matters: publishing twice must not churn."""
    ranks = initial(6)
    assert repair(ranks) == ranks


def test_moving_one_tile_rewrites_one_rank():
    """The whole reason ranks are fractional — one moved tile, one changed file."""
    ranks = initial(5)
    moved = [ranks[3]] + ranks[:3] + ranks[4:]
    out = repair(moved)
    assert out == sorted(out)
    assert sum(1 for before, after in zip(moved, out) if before != after) == 1


def test_new_tile_does_not_disturb_its_neighbours():
    ranks = initial(4)
    with_new = ranks[:2] + [None] + ranks[2:]
    out = repair(with_new)
    assert out == sorted(out)
    assert [out[0], out[1], out[3], out[4]] == ranks


def test_first_publish_ranks_a_whole_board():
    out = repair([None] * 6)
    assert len(set(out)) == 6
    assert out == sorted(out)
    assert all(is_rank(r) for r in out)


def test_slugs_survive_being_checked_out_anywhere():
    assert slugify("IdeaBRD") == "ideabrd"
    assert slugify("NFL Projections!") == "nfl-projections"
    assert slugify("  --Spaced  Out--  ") == "spaced-out"
    # Accents fold rather than drop, so the name stays recognisable.
    assert slugify("Idée fixe") == "idee-fixe"
    # Nothing ASCII left, and names Windows refuses, both need a fallback.
    assert slugify("日本語") == "idea"
    assert slugify("🎉") == "idea"
    assert slugify("con") == "con-idea"
    assert len(slugify("x" * 200)) == 60
    for name in ("ideabrd", "nfl-projections", "a1", "con-idea"):
        assert is_slug(name)
    for name in ("", "-lead", "trail-", "Upper", "has space", "dot.name", "con"):
        assert not is_slug(name)


def test_slugs_are_unique_case_insensitively():
    """macOS and Windows fold case, so two directories differing only in case
    collide on exactly the machines this board is meant to be cloned onto."""
    taken = {"ideabrd"}
    assert unique_slug("IdeaBRD", taken) == "ideabrd-2"
    assert unique_slug("IdeaBRD", {"IDEABRD"}) == "ideabrd-2"
    assert unique_slug("IdeaBRD", {"ideabrd", "ideabrd-2"}) == "ideabrd-3"
    # The suffix fits inside the cap rather than pushing the name past it.
    assert len(unique_slug("x" * 200, {"x" * 60})) <= 60


def test_layout_paths():
    assert idea_file_path("ideabrd") == "ideas/ideabrd/IDEA.md"


def test_board_keys_are_written_only_when_given():
    """A linked repo's own IDEA.md must never sprout someone's board position:
    a shared idea sits on several boards, at a different place on each."""
    plain = render_idea_file(
        title="T", notes="", status="idea", progress=0, todos=[]
    )
    assert "rank:" not in plain and "color:" not in plain and "repo:" not in plain

    board_copy = render_idea_file(
        title="T",
        notes="",
        status="active",
        progress=40,
        todos=[("ship", False)],
        color="#6366f1",
        rank="a0m",
        repo="octocat/hello",
    )
    parsed = parse_idea_file(board_copy)
    assert (parsed.color, parsed.rank, parsed.repo) == ("#6366f1", "a0m", "octocat/hello")
    assert (parsed.status, parsed.progress, parsed.title) == ("active", 40, "T")
    assert parsed.todos == [("ship", False, None)]


def test_board_keys_are_dropped_when_unusable():
    """Same leniency the rest of the parser has: a bad value costs its own
    field, never the file."""
    parsed = parse_idea_file(
        "---\nstatus: active\nprogress: 10\ncolor: puce\nrank: not a rank!\n"
        "repo: not-a-repo\n---\n\n# T\n\nnotes\n"
    )
    assert parsed.color is None and parsed.rank is None and parsed.repo is None
    assert parsed.status == "active" and parsed.progress == 10
    assert parsed.notes == "notes"


def test_repo_key_is_normalized_like_everywhere_else():
    parsed = parse_idea_file(
        "---\nrepo: https://github.com/octocat/hello.git\n---\n\n# T\n"
    )
    assert parsed.repo == "octocat/hello"


def test_files_without_board_keys_still_parse():
    """Every IDEA.md already in the wild predates these keys."""
    parsed = parse_idea_file("---\nstatus: done\nprogress: 100\n---\n\n# Old\n\nnotes\n")
    assert parsed.color is None and parsed.rank is None and parsed.repo is None
    assert parsed.status == "done" and parsed.title == "Old"
