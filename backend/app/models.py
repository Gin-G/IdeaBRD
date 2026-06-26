from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
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
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ideas: Mapped[list[Idea]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Idea(Base):
    __tablename__ = "ideas"

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
    position: Mapped[int] = mapped_column(Integer, default=0)
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


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    idea_id: Mapped[int] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    idea: Mapped[Idea] = relationship(back_populates="todos")


class IdeaCollaborator(Base):
    """A user (other than the owner) granted access to a single idea."""

    __tablename__ = "idea_collaborators"
    __table_args__ = (UniqueConstraint("idea_id", "user_id", name="uq_idea_user"),)

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
