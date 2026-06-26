from __future__ import annotations

import re
import time

import httpx

from app.config import settings
from app.schemas import GitHubRepoOut

_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, GitHubRepoOut]] = {}

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


class GitHubError(Exception):
    """Raised when the GitHub API call fails or the repo reference is invalid."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def normalize_repo(repo: str) -> str:
    """Accept 'owner/name' or a full GitHub URL and return 'owner/name'."""
    repo = repo.strip()
    match = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", repo)
    if match:
        repo = match.group(1)
    if not _REPO_RE.match(repo):
        raise GitHubError(f"Invalid repo reference: {repo!r}", status_code=400)
    return repo


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def fetch_repo(repo: str, *, client: httpx.AsyncClient | None = None) -> GitHubRepoOut:
    """Fetch live repo data for 'owner/name', cached for a few minutes."""
    full_name = normalize_repo(repo)

    cached = _cache.get(full_name)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(f"/repos/{full_name}", headers=_headers())
        if resp.status_code == 404:
            raise GitHubError("Repository not found", status_code=404)
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        data = resp.json()

        last_commit_message = None
        commits = await client.get(
            f"/repos/{full_name}/commits",
            params={"per_page": 1},
            headers=_headers(),
        )
        if commits.status_code == 200 and commits.json():
            last_commit_message = (
                commits.json()[0].get("commit", {}).get("message", "").split("\n")[0]
            )
    except httpx.HTTPError as exc:  # network / unexpected status
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()

    result = GitHubRepoOut(
        full_name=data["full_name"],
        html_url=data["html_url"],
        description=data.get("description"),
        stars=data.get("stargazers_count", 0),
        open_issues=data.get("open_issues_count", 0),
        forks=data.get("forks_count", 0),
        language=data.get("language"),
        default_branch=data.get("default_branch", "main"),
        pushed_at=data.get("pushed_at"),
        last_commit_message=last_commit_message,
    )
    _cache[full_name] = (time.monotonic(), result)
    return result


def clear_cache() -> None:
    """Test helper to reset the in-memory cache."""
    _cache.clear()
