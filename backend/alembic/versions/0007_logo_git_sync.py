"""track the tile logo in the linked repo (idea_logo.<ext>)

Revision ID: 0007_logo_git_sync
Revises: 0006_idea_logos
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_logo_git_sync"
down_revision: Union[str, None] = "0006_idea_logos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ideas", sa.Column("github_logo_path", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "ideas", sa.Column("github_logo_sha", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ideas", "github_logo_sha")
    op.drop_column("ideas", "github_logo_path")
