from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import EDIT_ROLES, ROLE_OWNER, Idea, IdeaCollaborator, User


def can_edit(role: str | None) -> bool:
    return role in EDIT_ROLES


async def resolve_idea(
    session: AsyncSession,
    idea_id: int,
    user: User,
    *,
    with_todos: bool = False,
    fresh: bool = False,
) -> tuple[Idea | None, str | None]:
    """Return (idea, role) if the user is a member of the idea, else (None, None).

    role is "owner", "editor" or "viewer". Non-members get (None, None) so callers
    can return 404 without leaking the idea's existence. Pass fresh=True to
    overwrite already-loaded attributes/collections (e.g. after a git pull
    mutated todos outside the relationship).
    """
    stmt = select(Idea).where(Idea.id == idea_id)
    if with_todos:
        stmt = stmt.options(selectinload(Idea.todos))
    if fresh:
        stmt = stmt.execution_options(populate_existing=True)
    idea = (await session.execute(stmt)).scalar_one_or_none()
    if idea is None:
        return None, None
    if idea.user_id == user.id:
        return idea, ROLE_OWNER
    role = await session.scalar(
        select(IdeaCollaborator.role).where(
            IdeaCollaborator.idea_id == idea_id,
            IdeaCollaborator.user_id == user.id,
        )
    )
    if role is not None:
        return idea, role
    return None, None


async def idea_member_ids(session: AsyncSession, idea_id: int) -> list[int]:
    """All user ids with access to an idea (owner + collaborators), for broadcasts."""
    owner_id = await session.scalar(select(Idea.user_id).where(Idea.id == idea_id))
    if owner_id is None:
        return []
    collab_ids = (
        await session.execute(
            select(IdeaCollaborator.user_id).where(
                IdeaCollaborator.idea_id == idea_id
            )
        )
    ).scalars().all()
    return [owner_id, *collab_ids]


async def user_board_max_position(session: AsyncSession, user_id: int) -> int:
    """Highest grid position across a user's owned and shared ideas (-1 if empty)."""
    owned = await session.scalar(
        select(func.coalesce(func.max(Idea.position), -1)).where(
            Idea.user_id == user_id
        )
    )
    shared = await session.scalar(
        select(func.coalesce(func.max(IdeaCollaborator.position), -1)).where(
            IdeaCollaborator.user_id == user_id
        )
    )
    return max(owned, shared)
