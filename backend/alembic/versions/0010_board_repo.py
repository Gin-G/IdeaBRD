"""a board repo per user, and a board-local name for shared ideas

Two things the publisher needs that the schema had no room for. The first is
where a board goes: a repo the user nominates, plus enough state to tell our own
last publish apart from someone editing the files directly.

The second is subtler. ideas.slug is unique per *owner*, but a board carries
other people's ideas too, and two owners can each have an "ideabrd". The
directory has to be unique per board, so a shared tile gets its name on the
board that shows it rather than inheriting one that may already be taken.

Revision ID: 0010_board_repo
Revises: 0009_board_identity
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_board_repo"
down_revision: Union[str, None] = "0009_board_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("board_repo", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("board_branch", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("board_commit_sha", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("board_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "idea_collaborators", sa.Column("slug", sa.String(length=60), nullable=True)
    )
    # Left null and filled by the publisher, which is the only thing that knows
    # what else is already on that board.
    op.create_unique_constraint(
        "uq_collab_user_slug", "idea_collaborators", ["user_id", "slug"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_collab_user_slug", "idea_collaborators", type_="unique")
    op.drop_column("idea_collaborators", "slug")
    op.drop_column("users", "board_published_at")
    op.drop_column("users", "board_commit_sha")
    op.drop_column("users", "board_branch")
    op.drop_column("users", "board_repo")
