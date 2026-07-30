"""uploaded tile logos

Revision ID: 0006_idea_logos
Revises: 0005_normalize_github_repo
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_idea_logos"
down_revision: Union[str, None] = "0005_normalize_github_repo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "idea_logos",
        sa.Column("idea_id", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["idea_id"], ["ideas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("idea_id"),
    )


def downgrade() -> None:
    op.drop_table("idea_logos")
