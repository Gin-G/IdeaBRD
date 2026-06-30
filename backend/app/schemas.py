from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None = None
    avatar_url: str | None = None


class IdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    email: str | None = None
    github_login: str | None = None
    has_repo_token: bool = False


# ---- Todos ----


class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    done: bool
    position: int


class TodoCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class TodoUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None
    position: int | None = None


# ---- Ideas ----


class IdeaBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    notes: str = ""
    status: str = "idea"
    progress: int = Field(default=0, ge=0, le=100)
    color: str = "#6366f1"
    logo_url: str | None = None
    github_repo: str | None = None


class IdeaCreate(IdeaBase):
    pass


class IdeaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    status: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    color: str | None = None
    logo_url: str | None = None
    github_repo: str | None = None
    position: int | None = None


class OwnerInfo(BaseModel):
    name: str | None = None
    email: str
    avatar_url: str | None = None


class IdeaOut(IdeaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    created_at: datetime
    updated_at: datetime
    todos: list[TodoOut] = []
    # The requesting user's role for this idea: owner | editor | viewer.
    role: str = "owner"
    owner: OwnerInfo | None = None


class IdeaSummary(BaseModel):
    """Lightweight shape used for the board grid (no notes/todos payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    progress: int
    color: str
    logo_url: str | None = None
    github_repo: str | None = None
    position: int
    role: str = "owner"
    shared: bool = False  # True when this idea is shared WITH me (I'm a collaborator)
    has_collaborators: bool = False  # True when I own it and have invited others
    owner: OwnerInfo | None = None  # set when shared with me


class ReorderItem(BaseModel):
    id: int
    position: int


# ---- Collaborators ----


class CollaboratorOut(BaseModel):
    # "active" = a real member; "pending" = an emailed invite not yet claimed
    status: str
    role: str
    email: str
    user_id: int | None = None
    name: str | None = None
    avatar_url: str | None = None
    invite_id: int | None = None
    is_owner: bool = False


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "editor"


# ---- GitHub ----


class GitHubRepoOut(BaseModel):
    full_name: str
    html_url: str
    description: str | None = None
    stars: int
    open_issues: int
    forks: int
    language: str | None = None
    default_branch: str
    pushed_at: str | None = None
    last_commit_message: str | None = None
