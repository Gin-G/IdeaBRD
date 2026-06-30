"""identities (multi-provider login) + drop users.google_sub

Revision ID: 0003_identities
Revises: 0002_collaborators
Create Date: 2026-06-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_identities"
down_revision: Union[str, None] = "0002_collaborators"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("github_login", sa.String(length=255), nullable=True),
        sa.Column("github_token", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_provider_subject"),
    )
    op.create_index(op.f("ix_identities_user_id"), "identities", ["user_id"])

    # Backfill a google identity for every existing user.
    op.execute(
        "INSERT INTO identities (user_id, provider, subject, email, created_at) "
        "SELECT id, 'google', google_sub, email, now() FROM users"
    )

    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("google_sub", sa.String(length=255), nullable=True)
    )
    op.execute(
        "UPDATE users SET google_sub = i.subject FROM identities i "
        "WHERE i.user_id = users.id AND i.provider = 'google'"
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.drop_index(op.f("ix_identities_user_id"), table_name="identities")
    op.drop_table("identities")
