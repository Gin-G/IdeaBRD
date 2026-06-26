from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket

from app.access import idea_member_ids


class ConnectionManager:
    """Tracks active WebSocket connections per user id (in-memory, single replica)."""

    def __init__(self) -> None:
        self._active: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._active[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        conns = self._active.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._active.pop(user_id, None)

    async def send_to_users(self, user_ids: list[int], message: dict) -> None:
        data = json.dumps(message)
        for uid in set(user_ids):
            for ws in list(self._active.get(uid, ())):
                try:
                    await ws.send_text(data)
                except Exception:
                    self.disconnect(uid, ws)


manager = ConnectionManager()


async def notify_idea(
    session: AsyncSession, idea_id: int, action: str, member_ids: list[int] | None = None
) -> None:
    """Broadcast an idea change to all of its members.

    Pass member_ids explicitly when the idea (and its membership) is about to be
    deleted, since they can't be looked up afterwards.
    """
    ids = member_ids if member_ids is not None else await idea_member_ids(session, idea_id)
    if ids:
        await manager.send_to_users(ids, {"type": "idea", "action": action, "id": idea_id})


async def notify_board(user_ids: list[int]) -> None:
    """Tell specific users to refetch their board (e.g. when sharing changes)."""
    if user_ids:
        await manager.send_to_users(user_ids, {"type": "board"})
