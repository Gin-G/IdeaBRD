from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import resolve_idea
from app.auth import get_current_user
from app.db import get_session
from app.github import GitHubError, fetch_repo
from app.models import User
from app.schemas import GitHubRepoOut

router = APIRouter(prefix="/api/ideas", tags=["github"])


@router.get("/{idea_id}/github", response_model=GitHubRepoOut)
async def idea_github(
    idea_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Live GitHub data for the repo linked to an idea (any member may view)."""
    idea, _role = await resolve_idea(session, idea_id, user)
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    if not idea.github_repo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Idea has no linked GitHub repo",
        )
    try:
        return await fetch_repo(idea.github_repo)
    except GitHubError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
