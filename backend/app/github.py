from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass

import httpx

from app.config import settings
from app.repo_ref import InvalidRepoRef
from app.repo_ref import normalize_repo as _normalize_repo
from app.schemas import GitHubRepoOut

_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, GitHubRepoOut]] = {}

# Issues pulled per sync. One page keeps the pull to a single request per open.
_ISSUE_PAGE_SIZE = 100


class GitHubError(Exception):
    """Raised when the GitHub API call fails or the repo reference is invalid."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def normalize_repo(repo: str) -> str:
    """Accept 'owner/name' or a full GitHub URL and return 'owner/name'.

    Wraps the shared parser so API callers keep seeing a GitHubError.
    """
    try:
        return _normalize_repo(repo)
    except InvalidRepoRef as exc:
        raise GitHubError(str(exc), status_code=400) from exc


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


async def list_dir(
    repo: str,
    path: str = "",
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, tuple[str, int]]:
    """Map file name -> (blob sha, size) for a directory. Empty when it's absent.

    One listing answers "does the repo have a logo, and has it changed?" without
    downloading the image, since the entry carries the blob sha.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/contents/{path}", headers=_headers(token)
        )
        if resp.status_code == 404:
            return {}
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):  # path is a file
            raise GitHubError(f"{path} is a file, not a directory", status_code=400)
        return {
            entry["name"]: (entry["sha"], entry.get("size", 0))
            for entry in data
            if entry.get("type") == "file"
        }
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def get_blob(
    repo: str,
    sha: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Fetch raw blob bytes by sha.

    The blobs API is used rather than the Contents API because the latter stops
    inlining content above 1MB, which is exactly the size range logos live in.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/git/blobs/{sha}", headers=_headers(token)
        )
        if resp.status_code == 404:
            raise GitHubError("Blob not found", status_code=404)
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        data = resp.json()
        if data.get("encoding") != "base64":
            raise GitHubError(f"Unsupported blob encoding: {data.get('encoding')}")
        return base64.b64decode(data.get("content", "") or "")
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def put_file(
    repo: str,
    path: str,
    content: str | bytes,
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
    raw = content.encode("utf-8") if isinstance(content, str) else content
    body: dict[str, str] = {
        "message": message,
        "content": base64.b64encode(raw).decode("ascii"),
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


async def delete_file(
    repo: str,
    path: str,
    message: str,
    *,
    sha: str,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Delete a file via the Contents API. A 409/422 means the sha is stale."""
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.request(
            "DELETE",
            f"/repos/{full_name}/contents/{path}",
            headers=_headers(token),
            json={"message": message, "sha": sha},
        )
        if resp.status_code == 404:
            return  # already gone; nothing to undo
        if resp.status_code in (409, 422):
            raise GitHubError("File changed on GitHub since last sync", status_code=409)
        if resp.status_code in (401, 403):
            raise GitHubError("GitHub token lacks write access", status_code=403)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


@dataclass(frozen=True)
class Issue:
    """The parts of a GitHub issue a to-do is made of."""

    number: int
    title: str
    state: str  # "open" | "closed"
    html_url: str


def _issue(data: dict) -> Issue:
    return Issue(
        number=data["number"],
        title=data.get("title") or "",
        state=data.get("state") or "open",
        html_url=data.get("html_url") or "",
    )


async def list_issues(
    repo: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[int, Issue]:
    """Map issue number -> Issue for the repo's most recent issues.

    Pull requests are filtered out: this endpoint returns them alongside issues,
    and a PR sharing a number with a to-do would otherwise drive its state.

    One page only. A to-do pointing at an issue older than that keeps whatever
    state it already had rather than being reported wrong, and app-side edits
    still reach the right issue — only the pull goes stale.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/issues",
            params={"state": "all", "per_page": _ISSUE_PAGE_SIZE},
            headers=_headers(token),
        )
        if resp.status_code == 404:
            return {}
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        return {
            entry["number"]: _issue(entry)
            for entry in resp.json()
            if "pull_request" not in entry
        }
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def create_issue(
    repo: str,
    title: str,
    body: str = "",
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Issue:
    """Open an issue and return it."""
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.post(
            f"/repos/{full_name}/issues",
            headers=_headers(token),
            json={"title": title, "body": body},
        )
        if resp.status_code in (401, 403):
            raise GitHubError("GitHub token lacks issue write access", status_code=403)
        if resp.status_code == 404:
            raise GitHubError("Repository not found or no write access", status_code=404)
        if resp.status_code == 410:
            raise GitHubError("Issues are disabled for this repository", status_code=400)
        resp.raise_for_status()
        return _issue(resp.json())
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def update_issue(
    repo: str,
    number: int,
    *,
    title: str | None = None,
    state: str | None = None,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Issue:
    """Patch an issue's title and/or open/closed state."""
    body: dict[str, str] = {}
    if title is not None:
        body["title"] = title
    if state is not None:
        body["state"] = state
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.patch(
            f"/repos/{full_name}/issues/{number}",
            headers=_headers(token),
            json=body,
        )
        if resp.status_code == 404:
            raise GitHubError("Issue not found or no write access", status_code=404)
        if resp.status_code in (401, 403):
            raise GitHubError("GitHub token lacks issue write access", status_code=403)
        resp.raise_for_status()
        return _issue(resp.json())
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


def clear_cache() -> None:
    """Test helper to reset the in-memory cache."""
    _cache.clear()
