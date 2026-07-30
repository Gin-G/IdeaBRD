"""Parsing for GitHub repo references.

Lives apart from ``app.github`` so the request schemas can normalize a repo on
the way in — ``app.github`` imports ``app.schemas``, so it cannot be imported
from there without a cycle.
"""

from __future__ import annotations

import re

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_URL_RE = re.compile(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


class InvalidRepoRef(ValueError):
    """The given string is not a usable ``owner/name`` reference."""


def normalize_repo(repo: str) -> str:
    """Accept 'owner/name' or a full GitHub URL and return 'owner/name'.

    Stored values must be normalized: the UI interpolates them straight into
    ``https://github.com/{repo}`` hrefs, so a full clone URL doubles up.
    """
    repo = repo.strip()
    match = _URL_RE.search(repo)
    if match:
        repo = match.group(1)
    if not _REPO_RE.match(repo):
        raise InvalidRepoRef(f"Invalid repo reference: {repo!r}")
    return repo
