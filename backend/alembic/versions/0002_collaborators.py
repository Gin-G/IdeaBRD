"""collaborators and invitations

Revision ID: 0002_collaborators
Revises: 0001_initial
Create Date: 2026-06-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_collaborators"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idea_collaborators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idea_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False, server_default="editor"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["idea_id"], ["ideas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idea_id", "user_id", name="uq_idea_user"),
    )
    op.create_index(
        op.f("ix_idea_collaborators_idea_id"), "idea_collaborators", ["idea_id"]
    )
    op.create_index(
        op.f("ix_idea_collaborators_user_id"), "idea_collaborators", ["user_id"]
    )

    op.create_table(
        "idea_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idea_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False, server_default="editor"),
        sa.Column("invited_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["idea_id"], ["ideas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idea_id", "email", name="uq_idea_email"),
    )
    op.create_index(
        op.f("ix_idea_invitations_idea_id"), "idea_invitations", ["idea_id"]
    )
    op.create_index(
        op.f("ix_idea_invitations_email"), "idea_invitations", ["email"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_idea_invitations_email"), table_name="idea_invitations")
    op.drop_index(op.f("ix_idea_invitations_idea_id"), table_name="idea_invitations")
    op.drop_table("idea_invitations")
    op.drop_index(
        op.f("ix_idea_collaborators_user_id"), table_name="idea_collaborators"
    )
    op.drop_index(
        op.f("ix_idea_collaborators_idea_id"), table_name="idea_collaborators"
    )
    op.drop_table("idea_collaborators")
