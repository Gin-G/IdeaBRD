"""The board repo: where a whole board is published as files.

An idea's own repo is linked per idea (see routers/repos.py); this is the one
repo that holds the *board* — every tile, in the layout app.boardrepo defines.
Publishing is explicit while the database is still authoritative: nothing here
runs on a timer, so a board is only ever written when someone asks for it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_session
from app.github import GitHubError, create_repo, fetch_repo, list_orgs, whoami
from app.models import User
from app.publisher import DEFAULT_BRANCH, board_token, publish_board
from app.schemas import (
    BoardInit,
    BoardInitOut,
    BoardOut,
    BoardOwner,
    BoardOwnersOut,
    BoardRepoUpdate,
    PublishOut,
)

router = APIRouter(prefix="/api/board", tags=["board"])


@router.get("", response_model=BoardOut)
async def get_board(user: User = Depends(get_current_user)):
    return BoardOut.model_validate(user)


@router.put("", response_model=BoardOut)
async def set_board_repo(
    payload: BoardRepoUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Nominate the repo this board publishes to.

    The repo is looked up rather than taken on trust, both to fail early on a
    typo and to learn its default branch — publishing to "main" in a repo whose
    branch is "master" would quietly create a second one.
    """
    if payload.board_repo is None:
        user.board_repo = user.board_branch = None
    else:
        try:
            info = await fetch_repo(payload.board_repo)
        except GitHubError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        user.board_repo = info.full_name
        user.board_branch = info.default_branch or DEFAULT_BRANCH
    # A different repo has never been published to, whatever we last recorded.
    user.board_commit_sha = None
    user.board_published_at = None
    await session.commit()
    return BoardOut.model_validate(user)


@router.post("/publish", response_model=PublishOut)
async def publish(
    opt_in: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Write the board to its repo. ``opt_in`` accepts publishing into a repo
    that already holds files but is not yet a board."""
    if not user.board_repo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No board repo configured",
        )
    result = await publish_board(session, user, opt_in=opt_in)
    return PublishOut(**vars(result))


async def _require_token(session: AsyncSession, user: User) -> str:
    token = await board_token(session, user)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect a GitHub account first",
        )
    return token


@router.get("/owners", response_model=BoardOwnersOut)
async def board_owners(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Accounts a board repo could be created under: the user, plus their orgs."""
    token = await _require_token(session, user)
    try:
        login, scopes = await whoami(token)
        orgs = await list_orgs(token) if "read:org" in scopes else []
    except GitHubError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return BoardOwnersOut(
        owners=[BoardOwner(login=login, kind="user")]
        + [BoardOwner(login=o, kind="org") for o in orgs],
        orgs_visible="read:org" in scopes,
    )


@router.post("/init", response_model=BoardInitOut)
async def init_board(
    payload: BoardInit,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a fresh repo for this board and publish into it.

    Publishing opts in without asking: the gate exists to stop the app writing
    into a repo somebody already had, and this one did not exist a moment ago.
    """
    token = await _require_token(session, user)
    try:
        full_name, branch = await create_repo(
            payload.name,
            org=payload.org or None,
            private=payload.private,
            description="IdeaBRD board",
            token=token,
        )
    except GitHubError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    user.board_repo = full_name
    user.board_branch = branch or DEFAULT_BRANCH
    user.board_commit_sha = None
    user.board_published_at = None
    await session.commit()

    result = await publish_board(session, user, opt_in=True)
    return BoardInitOut(
        board=BoardOut.model_validate(user), publish=PublishOut(**vars(result))
    )
