from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Roles. "owner" is implicit (Idea.user_id); collaborators are "editor" or "viewer".
ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
EDIT_ROLES = (ROLE_OWNER, ROLE_EDITOR)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # The user's board repo: where the whole board is published as files, in the
    # layout app.boardrepo describes. Null until they choose one — the board
    # lives in Postgres either way, and git is a second copy until it is trusted.
    board_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    board_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Commit this board was last published as, so a later read can tell our own
    # writes apart from someone editing the repo directly.
    board_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    board_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ideas: Mapped[list[Idea]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    identities: Mapped[list[Identity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Identity(Base):
    """A federated login (Google or GitHub) attached to a user. A user may have several."""

    __tablename__ = "identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_provider_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20))  # "google" | "github"
    subject: Mapped[str] = mapped_column(String(255))  # provider's stable user id
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # OAuth access token (used for repo file sync). Stored as-is; see SECURITY note in README.
    github_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="identities")


class Idea(Base):
    __tablename__ = "ideas"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_idea_user_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="")
    # idea | active | paused | done
    status: Mapped[str] = mapped_column(String(20), default="idea")
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    color: Mapped[str] = mapped_column(String(20), default="#6366f1")
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # "owner/name" form, or null for note-only tiles
    github_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Blob sha of IDEA.md at the last successful git sync (null = never synced)
    github_file_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Repo path and blob sha of the synced tile logo, e.g. "idea_logo.png".
    # Both null = the logo (if any) is app-only and not tracked in the repo.
    github_logo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_logo_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Board-repo identity: the directory this idea occupies (ideas/<slug>/) and
    # its fractional rank on the owner's board. Both are assigned by the
    # publisher rather than the request path, so nothing about the live site's
    # writes changes while the git copy is still earning trust. Null means the
    # idea has never been published. See app.boardrepo and app.rank.
    slug: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rank: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="ideas")
    todos: Mapped[list[Todo]] = relationship(
        back_populates="idea",
        cascade="all, delete-orphan",
        order_by="Todo.position",
    )
    collaborators: Mapped[list[IdeaCollaborator]] = relationship(
        back_populates="idea", cascade="all, delete-orphan"
    )
    invitations: Mapped[list[IdeaInvitation]] = relationship(
        back_populates="idea", cascade="all, delete-orphan"
    )
    logo: Mapped[IdeaLogo | None] = relationship(
        back_populates="idea", cascade="all, delete-orphan", uselist=False
    )


class IdeaLogo(Base):
    """An uploaded tile logo, kept out of the ideas row so board listings stay light.

    Postgres is the only storage this deployment has; images are capped at a
    size where a bytea column is the pragmatic home for them.
    """

    __tablename__ = "idea_logos"

    idea_id: Mapped[int] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(String(100))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    idea: Mapped[Idea] = relationship(back_populates="logo")


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Issue in the idea's linked repo backing this to-do, once promoted. While
    # set, the issue is authoritative for both text and done (open/closed) —
    # unlike a plain to-do, which the board owns.
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_issue_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    idea: Mapped[Idea] = relationship(back_populates="todos")


class IdeaCollaborator(Base):
    """A user (other than the owner) granted access to a single idea."""

    __tablename__ = "idea_collaborators"
    __table_args__ = (
        UniqueConstraint("idea_id", "user_id", name="uq_idea_user"),
        UniqueConstraint("user_id", "slug", name="uq_collab_user_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10), default=ROLE_EDITOR)
    # The collaborator's own grid position on their board.
    position: Mapped[int] = mapped_column(Integer, default=0)
    # ...and its fractional form, for the collaborator's own board repo. A
    # shared idea sits at a different place on every board that carries it,
    # which is exactly why rank can't live in the idea's own file.
    rank: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Directory this idea occupies on *this* collaborator's board. Idea.slug is
    # only unique per owner, so a shared idea can arrive at a board that already
    # has that directory; it gets its own name here rather than a collision.
    slug: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    idea: Mapped[Idea] = relationship(back_populates="collaborators")
    user: Mapped[User] = relationship()


class IdeaInvitation(Base):
    """A pending invite to an email that has no account yet (claimed on first login)."""

    __tablename__ = "idea_invitations"
    __table_args__ = (UniqueConstraint("idea_id", "email", name="uq_idea_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(10), default=ROLE_EDITOR)
    invited_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    idea: Mapped[Idea] = relationship(back_populates="invitations")
