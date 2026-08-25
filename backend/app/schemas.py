from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.repo_ref import InvalidRepoRef, normalize_repo


def _normalized_repo(value: str | None) -> str | None:
    """Store repos as 'owner/name'; treat blank as unlinked."""
    if value is None or not value.strip():
        return None
    try:
        return normalize_repo(value)
    except InvalidRepoRef as exc:
        raise ValueError(str(exc)) from exc


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
    # Set once the to-do has been promoted to an issue in the idea's repo, or
    # imported from one. Mirrored from GitHub and read-only here.
    github_issue_number: int | None = None
    github_issue_url: str | None = None
    github_issue_labels: list[str] | None = None
    github_issue_assignee: str | None = None
    github_issue_comments: int | None = None


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

    _normalize_github_repo = field_validator("github_repo")(_normalized_repo)


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

    _normalize_github_repo = field_validator("github_repo")(_normalized_repo)


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
    # Git sync state (repo-linked ideas): last successful IDEA.md sync, the
    # error from the most recent attempt (not persisted; set per-request), and
    # whether the repo has no IDEA.md yet (tracking awaits the user's opt-in).
    git_synced_at: datetime | None = None
    git_sync_error: str | None = None
    git_file_missing: bool = False


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


class PullRequestOut(BaseModel):
    """An open pull request on an idea's repo — where its collaboration happens."""

    number: int
    title: str
    html_url: str
    author: str | None = None
    draft: bool = False
    updated_at: str | None = None


class ImportIssuesOut(BaseModel):
    """Result of adopting a repo's issues as to-dos."""

    imported: int = 0
    todos: list[TodoOut] = Field(default_factory=list)


class IdeaRepoInit(BaseModel):
    """Give a note-only idea a repository of its own."""

    name: str = Field(min_length=1, max_length=100)
    org: str | None = None
    private: bool = True


class WebhookResult(BaseModel):
    """What a webhook delivery did, echoed back into GitHub's delivery log."""

    event: str
    # False for an event we take no interest in; the delivery still succeeded.
    handled: bool = False
    ideas: int = 0


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


# ---- Board repo ----


class BoardOut(BaseModel):
    """Where a user's board is published, and what happened last time."""

    model_config = ConfigDict(from_attributes=True)

    board_repo: str | None = None
    board_branch: str | None = None
    board_commit_sha: str | None = None
    board_published_at: datetime | None = None
    # Filled in by the API from the background publisher's in-memory state.
    sync: "BoardSyncOut | None" = None


class BoardRepoUpdate(BaseModel):
    # Blank clears the link, matching how an idea's own repo is unset.
    board_repo: str | None = None

    _normalize = field_validator("board_repo")(_normalized_repo)


class PublishOut(BaseModel):
    """Outcome of a publish. ``committed`` is false when nothing had changed."""

    committed: bool = False
    commit_sha: str | None = None
    written: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    # The repo holds files but isn't a board yet; publishing needs opt_in.
    needs_opt_in: bool = False
    # The repo moved since our last publish — someone committed to it directly.
    # Nothing was written; publishing over it needs ``force``.
    moved: bool = False
    head_sha: str | None = None
    error: str | None = None


class BoardOwner(BaseModel):
    """Somewhere a board repo could be created."""

    login: str
    kind: str  # "user" | "org"


class BoardOwnersOut(BaseModel):
    owners: list[BoardOwner] = Field(default_factory=list)
    # False when the GitHub login predates the read:org scope, in which case
    # only the personal account is listed and reconnecting adds the rest.
    orgs_visible: bool = True


class BoardInit(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Blank/None means the user's own account rather than an organisation.
    org: str | None = None
    private: bool = True


class BoardInitOut(BaseModel):
    board: BoardOut
    publish: PublishOut


class ReconcileEntry(BaseModel):
    """One idea, as the database and the board repo each have it."""

    slug: str
    title: str | None = None
    idea_id: int | None = None
    # same | differs | missing_in_repo | missing_in_board
    state: str
    # Field names that disagree, e.g. ["status", "todos"]. Empty unless differs.
    differences: list[str] = Field(default_factory=list)


class ReconcileOut(BaseModel):
    """Whether the board repo still says what the database says.

    Cutting over to git means trusting the repo. This is the evidence for that
    decision: every idea, on both sides, and what disagrees.
    """

    repo: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    # True when nothing disagrees: the repo is a faithful copy of the board.
    in_sync: bool = False
    # Set when the repo moved since our last publish (someone edited it directly).
    moved: bool = False
    entries: list[ReconcileEntry] = Field(default_factory=list)
    error: str | None = None


class BoardSyncOut(BaseModel):
    """State of the background dual-write for this board."""

    # True while a publish is queued or running for this user.
    pending: bool = False
    last_error: str | None = None
    last_commit_sha: str | None = None
