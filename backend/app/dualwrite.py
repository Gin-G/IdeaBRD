"""Dual-write: every board change also lands in the board repo.

Publishing has been an explicit button so far, which was the right shape while
the repo was a demonstration. It is the wrong shape for a copy that is supposed
to earn trust: a board published on Tuesday and edited on Wednesday proves only
that the publisher works, not that git holds the board. So every mutation now
schedules a publish, and Postgres stays authoritative while the two are kept
level — that is what "dual-write" means here, and it is the step before the
database can be retired at all.

Three things make this safe to hang off the request path:

**It is not on the request path.** A publish runs in a background task with its
own session, so a slow or broken GitHub never slows an edit or fails it. The
board is in Postgres; the repo catching up a second later costs nothing.

**Writes coalesce.** Dragging a tile across a board is a dozen mutations in a
second, and each one would otherwise be a commit. A short debounce collapses a
burst into one publish, and a change arriving *during* a publish schedules
exactly one more — never a queue of them.

**Nothing is written twice.** ``publish_board`` diffs the tree it finds against
the board it renders, so a publish with nothing to say makes no commit. A board
that is already level costs two API calls and no history.

Failures are recorded rather than raised, and read back through ``/api/board``:
a dual-write that quietly stopped working would be the one thing that could
make the git copy *less* trustworthy than no copy at all.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.publisher import publish_board

log = logging.getLogger(__name__)

# Long enough to swallow a drag or a burst of typing, short enough that the
# repo is level by the time anyone switches windows to look at it.
DEBOUNCE_SECONDS = 2.0

MOVED_MESSAGE = (
    "The board repo has commits the app didn't make, so publishing was skipped "
    "to avoid overwriting them. Review the differences, then publish anyway."
)


@dataclass
class SyncState:
    """What the background publisher last managed for one board."""

    pending: bool = False
    last_error: str | None = None
    last_commit_sha: str | None = None


_state: dict[int, SyncState] = {}
_workers: dict[int, asyncio.Task] = {}
_dirty: set[int] = set()


def state_for(user_id: int) -> SyncState:
    return _state.get(user_id, SyncState())


def reset() -> None:
    """Drop all state and workers. For tests."""
    for task in list(_workers.values()):
        task.cancel()
    _workers.clear()
    _dirty.clear()
    _state.clear()


async def boards_to_publish(session: AsyncSession, user_ids: Iterable[int]) -> list[int]:
    """Which of these users actually have somewhere to publish to."""
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return []
    return list(
        (
            await session.execute(
                select(User.id).where(User.id.in_(ids), User.board_repo.is_not(None))
            )
        )
        .scalars()
        .all()
    )


def schedule(user_ids: Iterable[int]) -> None:
    """Queue a publish for each board, coalescing with any already queued."""
    if not settings.board_dual_write:
        return
    for user_id in set(user_ids):
        _dirty.add(user_id)
        _state.setdefault(user_id, SyncState()).pending = True
        worker = _workers.get(user_id)
        if worker is None or worker.done():
            _workers[user_id] = asyncio.create_task(_worker(user_id))


async def after_idea_change(
    session: AsyncSession, member_ids: Iterable[int]
) -> None:
    """Dual-write an idea change to every board that shows it.

    A shared idea sits on the owner's board and each collaborator's, at
    different positions, so one edit is a change to several repos.
    """
    schedule(await boards_to_publish(session, member_ids))


async def _worker(user_id: int) -> None:
    """Publish this board until no further change is waiting."""
    try:
        while user_id in _dirty:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            # Cleared before the board is read, so a change that lands during
            # the publish schedules another round rather than being lost.
            _dirty.discard(user_id)
            await _publish(user_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # pragma: no cover - a background task must not die quietly
        log.exception("Dual-write failed for user %s", user_id)
    finally:
        _workers.pop(user_id, None)
        if user_id not in _dirty:
            _state.setdefault(user_id, SyncState()).pending = False


async def _publish(user_id: int) -> None:
    state = _state.setdefault(user_id, SyncState())
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None or not user.board_repo:
            state.last_error = None
            return
        result = await publish_board(session, user)
    if result.moved:
        state.last_error = MOVED_MESSAGE
    elif result.needs_opt_in:
        state.last_error = (
            "The board repo holds files that aren't a board, so nothing was "
            "written. Publish once from the board settings to opt in."
        )
    else:
        state.last_error = result.error
        if result.commit_sha:
            state.last_commit_sha = result.commit_sha


async def drain(timeout: float = 30.0) -> None:
    """Wait for every queued publish to finish. For tests and shutdown."""
    async with asyncio.timeout(timeout):
        while _workers:
            await asyncio.gather(*list(_workers.values()), return_exceptions=True)
