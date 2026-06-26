from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None = None
    avatar_url: str | None = None


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


class IdeaOut(IdeaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    created_at: datetime
    updated_at: datetime
    todos: list[TodoOut] = []


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


class ReorderItem(BaseModel):
    id: int
    position: int


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
