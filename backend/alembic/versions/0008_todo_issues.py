"""back a to-do with a GitHub issue

Revision ID: 0008_todo_issues
Revises: 0007_logo_git_sync
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_todo_issues"
down_revision: Union[str, None] = "0007_logo_git_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "todos", sa.Column("github_issue_number", sa.Integer(), nullable=True)
    )
    op.add_column(
        "todos", sa.Column("github_issue_url", sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("todos", "github_issue_url")
    op.drop_column("todos", "github_issue_number")
