"""backfill ideas.github_repo to the owner/name form

Rows created before the write path normalized this column hold whatever was
typed, usually a full clone URL. The UI interpolates the value straight into
``https://github.com/{repo}``, so those rows render doubled, broken links.

Revision ID: 0005_normalize_github_repo
Revises: 0004_git_sync
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_normalize_github_repo"
down_revision: Union[str, None] = "0004_git_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Strip a leading scheme/host (https://github.com/ or git@github.com:), any
    # trailing .git and trailing slash. Only touches rows that still carry a
    # host, so already-normalized values are left alone.
    op.execute(
        r"""
        UPDATE ideas
           SET github_repo = regexp_replace(
                   regexp_replace(github_repo, '^.*github\.com[/:]', ''),
                   '(\.git)?/?$', ''
               )
         WHERE github_repo IS NOT NULL
           AND github_repo ~ 'github\.com[/:]'
        """
    )


def downgrade() -> None:
    # The original text is not recoverable; owner/name is valid input either way.
    pass
