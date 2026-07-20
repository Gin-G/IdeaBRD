from __future__ import annotations

import base64
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


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = token or settings.github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


async def get_file(
    repo: str,
    path: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str] | None:
    """Fetch a file via the Contents API. Returns (text, blob_sha), or None if absent."""
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/contents/{path}", headers=_headers(token)
        )
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):  # path is a directory
            raise GitHubError(f"{path} is a directory, not a file", status_code=400)
        text = base64.b64decode(data.get("content", "") or "").decode("utf-8")
        return text, data["sha"]
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def put_file(
    repo: str,
    path: str,
    content: str,
    message: str,
    *,
    sha: str | None = None,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Create or update a file via the Contents API. Returns the new blob sha.

    Pass the current blob sha when updating; omit it when creating. A 409/422
    means the sha is stale (the file changed underneath us).
    """
    full_name = normalize_repo(repo)
    body: dict[str, str] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.put(
            f"/repos/{full_name}/contents/{path}", headers=_headers(token), json=body
        )
        if resp.status_code in (409, 422):
            raise GitHubError("File changed on GitHub since last sync", status_code=409)
        if resp.status_code in (401, 403):
            raise GitHubError("GitHub token lacks write access", status_code=403)
        if resp.status_code == 404:
            raise GitHubError("Repository not found or no write access", status_code=404)
        resp.raise_for_status()
        return resp.json()["content"]["sha"]
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


def clear_cache() -> None:
    """Test helper to reset the in-memory cache."""
    _cache.clear()
