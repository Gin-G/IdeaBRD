"""Who is signed in, held in memory and nowhere else.

With the database gone there is no users table to look an id up in, so a
session has to carry the identity itself: the GitHub login, the token that
speaks for it, and which repository is their board.

That could ride in the cookie, encrypted. It doesn't, deliberately. A cookie is
a copy of the credential that outlives the process and travels on every
request, so a browser profile, a backup of one, or a proxy that logs headers
becomes a working GitHub token. Here the cookie holds nothing but an opaque
id — useless to anyone who cannot also reach this process — and the token
never leaves the server.

The price is that a restart signs everybody out. That is a real cost and worth
stating plainly: the browser is bounced back through GitHub, which returns
without asking anything because the app is already authorised, and the phone
never notices because it holds its own token. Revocation, in exchange, is a
dictionary delete rather than a denylist that would put the state back.

Single process, single event loop: a plain dict is the right structure, and the
lack of a lock is deliberate rather than forgotten. A second replica would
break this, exactly as it would already break the Android hand-off codes.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

# A session nobody has used for this long is gone. Sessions rarely reach it —
# the process usually goes first — but an abandoned one should not sit in
# memory until it does.
IDLE_TTL_SECONDS = 7 * 24 * 60 * 60

# Enough for far more people than this will ever have. The cap exists so that
# something creating sessions in a loop cannot exhaust the pod.
MAX_SESSIONS = 10_000


@dataclass
class Session:
    """One signed-in person, for as long as this process lives."""

    login: str
    token: str
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    board_repo: str | None = None
    board_branch: str = "main"
    created: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)


_sessions: dict[str, Session] = {}


def _expired(session: Session, now: float) -> bool:
    return now - session.last_seen > IDLE_TTL_SECONDS


def sweep(now: float | None = None) -> int:
    """Drop everything idle past its welcome. Returns how many went."""
    moment = time.monotonic() if now is None else now
    stale = [sid for sid, s in _sessions.items() if _expired(s, moment)]
    for sid in stale:
        del _sessions[sid]
    return len(stale)


def create(session: Session) -> str:
    """Register a session and return the id the cookie will carry."""
    sweep()
    if len(_sessions) >= MAX_SESSIONS:
        # Oldest first: dicts keep insertion order, and the oldest session is
        # the one whose loss costs least.
        del _sessions[next(iter(_sessions))]
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = session
    return sid


def get(sid: str | None) -> Session | None:
    """The session behind an id, or None if there isn't one any more."""
    if not sid:
        return None
    session = _sessions.get(sid)
    if session is None:
        return None
    now = time.monotonic()
    if _expired(session, now):
        del _sessions[sid]
        return None
    session.last_seen = now
    return session


def drop(sid: str | None) -> None:
    """Sign one session out. What logout does."""
    if sid:
        _sessions.pop(sid, None)


def drop_login(login: str) -> int:
    """Sign out every session for a person. Returns how many."""
    theirs = [sid for sid, s in _sessions.items() if s.login == login]
    for sid in theirs:
        del _sessions[sid]
    return len(theirs)


def count() -> int:
    return len(_sessions)


def clear() -> None:
    """Forget everyone. For tests, and for a process shutting down."""
    _sessions.clear()
