"""one-time codes for handing a GitHub token to the Android app

The phone signs in by sending someone to the server's ordinary GitHub redirect
flow and catching the result on an Android App Link. The token itself must not
travel in that link: a redirect URL is visible to whatever handles it, and an
App Link is only exclusive once Google has verified the assetlinks file.

So the link carries a one-time code instead, and collecting the token means
proving possession of a secret the app generated and never sent — PKCE, with
the challenge stored here. Rows are deleted on use and expire in minutes.

Revision ID: 0012_android_handoff
Revises: 0011_issue_details
Create Date: 2026-08-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_android_handoff"
down_revision: Union[str, None] = "0011_issue_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "android_handoffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("challenge", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_android_handoffs_code"), "android_handoffs", ["code"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_android_handoffs_code"), table_name="android_handoffs")
    op.drop_table("android_handoffs")
