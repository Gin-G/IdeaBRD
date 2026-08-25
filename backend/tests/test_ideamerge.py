"""Merging two versions of an IDEA.md.

The property that matters is that nobody's edit disappears. Every test here is
a shape of "two people changed the file" — and the app is one of those people,
so an app push landing on a file somebody edited on GitHub has to keep both.
"""

from __future__ import annotations

from app.ideafile import parse_idea_file, render_idea_file
from app.ideamerge import merge_idea_files


def _file(
    *,
    title="Idea",
    notes="",
    status="active",
    progress=0,
    todos=(),
    guidance=False,
    **kw,
) -> str:
    return render_idea_file(
        title=title,
        notes=notes,
        status=status,
        progress=progress,
        todos=list(todos),
        guidance=guidance,
        **kw,
    )


def _merge(base, ours, theirs):
    text, parsed = merge_idea_files(base, ours, theirs, guidance=False)
    assert parse_idea_file(text).todos == parsed.todos, "render and parse must agree"
    return parsed


# ---- scalar fields ----


def test_each_side_keeps_the_field_only_it_changed():
    base = _file(status="idea", progress=0)
    ours = _file(status="active", progress=0)
    theirs = _file(status="idea", progress=60)
    merged = _merge(base, ours, theirs)
    assert (merged.status, merged.progress) == ("active", 60)


def test_git_wins_when_both_changed_the_same_field():
    """The file is the source of truth, so a pull would have imposed it anyway."""
    base = _file(status="idea")
    merged = _merge(base, _file(status="active"), _file(status="done"))
    assert merged.status == "done"


def test_a_title_renamed_on_github_survives_an_app_push():
    base = _file(title="Old")
    merged = _merge(base, _file(title="Old", status="done"), _file(title="New"))
    assert (merged.title, merged.status) == ("New", "done")


# ---- notes ----


def test_notes_edited_in_different_places_both_survive():
    base = _file(notes="one\ntwo\nthree")
    ours = _file(notes="one\ntwo\nthree\nfour")
    theirs = _file(notes="zero\none\ntwo\nthree")
    assert _merge(base, ours, theirs).notes == "zero\none\ntwo\nthree\nfour"


def test_notes_rewritten_on_both_sides_keeps_both():
    """Prose is the one field where a tie need not cost anyone their words."""
    base = _file(notes="original")
    merged = _merge(base, _file(notes="mine"), _file(notes="theirs"))
    assert merged.notes == "theirs\nmine"


# ---- to-dos ----


def test_additions_from_both_sides_are_kept():
    base = _file(todos=[("a", False)])
    ours = _file(todos=[("a", False), ("mine", False)])
    theirs = _file(todos=[("a", False), ("theirs", False)])
    merged = _merge(base, ours, theirs)
    # Ours lands directly after the item it followed here, rather than at the
    # end: an item added at the top of the board belongs at the top of the file.
    assert [t.text for t in merged.todos] == ["a", "mine", "theirs"]


def test_an_item_deleted_on_github_does_not_come_back():
    """The bug a two-way merge cannot avoid: our copy still has the item."""
    base = _file(todos=[("a", False), ("b", False)])
    ours = _file(todos=[("a", False), ("b", False)])
    theirs = _file(todos=[("a", False)])
    assert [t.text for t in _merge(base, ours, theirs).todos] == ["a"]


def test_an_item_deleted_in_the_app_stays_deleted():
    base = _file(todos=[("a", False), ("b", False)])
    ours = _file(todos=[("a", False)])
    theirs = _file(todos=[("a", False), ("b", False)])
    assert [t.text for t in _merge(base, ours, theirs).todos] == ["a"]


def test_a_box_ticked_on_github_wins_over_our_unticked_copy():
    base = _file(todos=[("a", False)])
    merged = _merge(base, _file(todos=[("a", False)]), _file(todos=[("a", True)]))
    assert merged.todos[0].done is True


def test_a_box_ticked_in_the_app_survives_an_unrelated_repo_edit():
    base = _file(todos=[("a", False), ("b", False)])
    ours = _file(todos=[("a", True), ("b", False)])
    theirs = _file(todos=[("a", False), ("b", True)])
    merged = _merge(base, ours, theirs)
    assert [(t.text, t.done) for t in merged.todos] == [("a", True), ("b", True)]


def test_an_issue_backed_item_is_matched_by_number_not_text():
    """Reworded on GitHub and reordered here: one item, not two."""
    base = _file(todos=[("old wording", False, 12)])
    ours = _file(todos=[("old wording", True, 12)])
    theirs = _file(todos=[("new wording", False, 12)])
    merged = _merge(base, ours, theirs)
    assert len(merged.todos) == 1
    assert merged.todos[0].text == "new wording"
    assert merged.todos[0].issue == 12


def test_without_a_base_nothing_is_dropped():
    """No common ancestor: an absence proves nothing, so both sides are kept."""
    ours = _file(todos=[("a", False), ("mine", False)])
    theirs = _file(todos=[("a", False), ("theirs", False)])
    merged = _merge(None, ours, theirs)
    assert {t.text for t in merged.todos} == {"a", "theirs", "mine"}


def test_board_keys_are_not_invented():
    """A linked repo's IDEA.md must not sprout somebody's board position."""
    text, _ = merge_idea_files(_file(), _file(status="done"), _file(), guidance=False)
    assert "rank:" not in text and "color:" not in text


def test_board_keys_survive_a_merge_of_board_files():
    base = _file(rank="a0", color="#111111")
    ours = _file(rank="a0", color="#222222")
    theirs = _file(rank="b0", color="#111111")
    merged = _merge(base, ours, theirs)
    assert (merged.rank, merged.color) == ("b0", "#222222")
