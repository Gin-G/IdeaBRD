"""git sync state on ideas (IDEA.md as source of truth)

Revision ID: 0004_git_sync
Revises: 0003_identities
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_git_sync"
down_revision: Union[str, None] = "0003_identities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ideas", sa.Column("github_file_sha", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "ideas", sa.Column("git_synced_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ideas", "git_synced_at")
    op.drop_column("ideas", "github_file_sha")
