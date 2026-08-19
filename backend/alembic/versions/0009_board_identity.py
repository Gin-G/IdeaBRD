"""give every idea a board-repo identity: slug and fractional rank

The git-only board names each idea by directory (ideas/<slug>/) and orders it
by a fractional rank held in its own file, so neither can be the serial primary
key or the dense ``position`` the app uses today — an id means nothing to
someone reading the repo, and renumbering positions rewrites every file below
an insert.

Both columns are nullable and both are filled here for existing rows, so the
first publish of an established board is a no-op rather than a churn of every
file. New ideas are left null until the publisher assigns them, which keeps the
live request paths out of this entirely.

Slugs come from app.boardrepo and ranks from app.rank. Importing app code into
a migration pins this backfill to today's behaviour, which is what we want: it
runs once per database, and later changes to slugging must not retroactively
rename directories that are already committed.

Revision ID: 0009_board_identity
Revises: 0008_todo_issues
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.boardrepo import unique_slug
from app.rank import initial

revision: str = "0009_board_identity"
down_revision: Union[str, None] = "0008_todo_issues"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ideas", sa.Column("slug", sa.String(length=60), nullable=True))
    op.add_column("ideas", sa.Column("rank", sa.String(length=64), nullable=True))
    op.add_column(
        "idea_collaborators", sa.Column("rank", sa.String(length=64), nullable=True)
    )

    conn = op.get_bind()

    # Slugs are unique per owner, so they're assigned one board at a time. The
    # id tiebreak keeps the result deterministic when two ideas share a title.
    rows = conn.execute(
        sa.text("SELECT id, user_id, title FROM ideas ORDER BY user_id, id")
    ).fetchall()
    taken: dict[int, set[str]] = {}
    for idea_id, user_id, title in rows:
        board = taken.setdefault(user_id, set())
        slug = unique_slug(title or "", board)
        board.add(slug)
        conn.execute(
            sa.text("UPDATE ideas SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": idea_id},
        )

    # Ranks are per board, and a board interleaves owned and shared ideas in one
    # position namespace (see list_ideas, which sorts them together). Ranking
    # the two sets separately would hand each of them the whole space and
    # scramble the order the user already has, so they're merged first.
    boards = conn.execute(
        sa.text(
            "SELECT DISTINCT user_id FROM ideas"
            " UNION SELECT DISTINCT user_id FROM idea_collaborators"
        )
    ).fetchall()
    for (user_id,) in boards:
        tiles = conn.execute(
            sa.text(
                "SELECT 'idea' AS kind, id, position FROM ideas WHERE user_id = :uid"
                " UNION ALL"
                " SELECT 'collab', id, position FROM idea_collaborators"
                " WHERE user_id = :uid"
                " ORDER BY position, kind, id"
            ),
            {"uid": user_id},
        ).fetchall()
        for (kind, row_id, _position), rank in zip(tiles, initial(len(tiles))):
            table = "ideas" if kind == "idea" else "idea_collaborators"
            conn.execute(
                sa.text(f"UPDATE {table} SET rank = :rank WHERE id = :id"),
                {"rank": rank, "id": row_id},
            )

    op.create_unique_constraint("uq_idea_user_slug", "ideas", ["user_id", "slug"])


def downgrade() -> None:
    op.drop_constraint("uq_idea_user_slug", "ideas", type_="unique")
    op.drop_column("idea_collaborators", "rank")
    op.drop_column("ideas", "rank")
    op.drop_column("ideas", "slug")
