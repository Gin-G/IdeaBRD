"""Sessions held in memory, which is the whole of the user table now.

The properties worth pinning down are the ones that replace a database: an id
nobody can guess, a session that ends when told to, and one that does not sit
in memory for ever because somebody closed a tab.
"""

from __future__ import annotations

import pytest

from app import sessions
from app.sessions import Session


@pytest.fixture(autouse=True)
def _empty():
    sessions.clear()
    yield
    sessions.clear()


def a_session(login: str = "octocat", **kwargs) -> Session:
    return Session(login=login, token=f"gho_{login}", **kwargs)


def test_a_session_comes_back_by_its_id():
    sid = sessions.create(a_session(board_repo="octocat/board"))

    found = sessions.get(sid)
    assert found is not None
    assert found.login == "octocat"
    assert found.token == "gho_octocat"
    assert found.board_repo == "octocat/board"


def test_an_id_nobody_handed_out_is_nobody():
    sessions.create(a_session())
    assert sessions.get("not-an-id") is None
    assert sessions.get(None) is None
    assert sessions.get("") is None


def test_ids_are_unguessable_and_unique():
    ids = {sessions.create(a_session()) for _ in range(200)}
    assert len(ids) == 200
    # token_urlsafe(32) is 256 bits; anything much shorter would be a mistake.
    assert all(len(i) >= 40 for i in ids)


def test_signing_out_ends_that_session_only():
    mine = sessions.create(a_session("me"))
    theirs = sessions.create(a_session("you"))

    sessions.drop(mine)

    assert sessions.get(mine) is None
    assert sessions.get(theirs) is not None


def test_a_person_can_be_signed_out_everywhere():
    """Revocation, which is the thing an encrypted cookie could not do."""
    phone = sessions.create(a_session("me"))
    laptop = sessions.create(a_session("me"))
    someone_else = sessions.create(a_session("you"))

    assert sessions.drop_login("me") == 2

    assert sessions.get(phone) is None
    assert sessions.get(laptop) is None
    assert sessions.get(someone_else) is not None


def test_an_idle_session_expires():
    sid = sessions.create(a_session())
    sessions.get(sid).last_seen -= sessions.IDLE_TTL_SECONDS + 1

    assert sessions.get(sid) is None
    assert sessions.count() == 0


def test_use_keeps_a_session_alive():
    sid = sessions.create(a_session())
    session = sessions.get(sid)
    session.last_seen -= sessions.IDLE_TTL_SECONDS - 60  # nearly, but not quite

    assert sessions.get(sid) is not None
    # Reading it just renewed the clock.
    assert sessions.get(sid).last_seen == pytest.approx(
        sessions.get(sid).last_seen, abs=1
    )


def test_sweeping_clears_out_the_abandoned():
    keep = sessions.create(a_session("here"))
    gone = sessions.create(a_session("gone"))
    sessions.get(gone).last_seen -= sessions.IDLE_TTL_SECONDS + 1

    assert sessions.sweep() == 1
    assert sessions.count() == 1
    assert sessions.get(keep) is not None


def test_the_store_is_bounded(monkeypatch):
    """Something creating sessions in a loop must not exhaust the pod."""
    monkeypatch.setattr(sessions, "MAX_SESSIONS", 5)

    ids = [sessions.create(a_session(f"n{i}")) for i in range(8)]

    assert sessions.count() == 5
    assert sessions.get(ids[0]) is None  # the oldest went first
    assert sessions.get(ids[-1]) is not None
