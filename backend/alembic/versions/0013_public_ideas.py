"""a public flag on ideas, and a site that can be public or not

The flag is written into the board repo as ``public: true`` on the owner's own
tiles, and the public page reads it from there; this column is what the web
app's toggle writes until the database is gone. Every existing idea starts
private.

``site`` is where an idea runs and ``site_public`` whether a public page may
link it. Both are idea-level, written into a linked repo's own IDEA.md, so a
site behind a login can sit on a public tile without being advertised.

Revision ID: 0013_public_ideas
Revises: 0012_android_handoff
Create Date: 2026-11-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_public_ideas"
down_revision: Union[str, None] = "0012_android_handoff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ideas",
        sa.Column("public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ideas", sa.Column("site", sa.String(length=1024), nullable=True))
    op.add_column(
        "ideas",
        sa.Column("site_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("ideas", "site_public")
    op.drop_column("ideas", "site")
    op.drop_column("ideas", "public")
