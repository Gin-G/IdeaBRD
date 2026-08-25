"""issue context on a to-do: labels, assignee, comment count

A to-do promoted to an issue was mirroring two fields — the title and whether
it is closed — which is enough to drive a checkbox and nothing more. The issue
itself carries the part that makes it worth looking at on a board: who owns it,
what it is filed under, and whether anyone is talking about it.

All three are mirrored from GitHub and never written back, so they are nullable
and stay null for a to-do that was never promoted.

Revision ID: 0011_issue_details
Revises: 0010_board_repo
Create Date: 2026-08-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_issue_details"
down_revision: Union[str, None] = "0010_board_repo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSON rather than a delimited string: a label may contain a comma, and a
    # board that renders "needs design, ux" as two labels is wrong in a way
    # nobody would think to check.
    op.add_column("todos", sa.Column("github_issue_labels", sa.JSON(), nullable=True))
    op.add_column(
        "todos", sa.Column("github_issue_assignee", sa.String(length=255), nullable=True)
    )
    op.add_column("todos", sa.Column("github_issue_comments", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("todos", "github_issue_comments")
    op.drop_column("todos", "github_issue_assignee")
    op.drop_column("todos", "github_issue_labels")
