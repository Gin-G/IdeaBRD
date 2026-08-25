from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx

from app.config import settings
from app.repo_ref import InvalidRepoRef
from app.repo_ref import normalize_repo as _normalize_repo
from app.schemas import GitHubRepoOut

_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, GitHubRepoOut]] = {}

# Issues pulled per sync. A page is the API's maximum; the cap bounds how many
# of them one open of a tile will ask for, so a repo with thousands of issues
# costs a predictable number of requests rather than an unbounded walk.
_ISSUE_PAGE_SIZE = 100
_ISSUE_MAX_PAGES = 10

# Open pull requests shown on a tile. A tile has room for a handful; the rest
# are a link away.
_PULL_PAGE_SIZE = 20


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
    """The parts of a GitHub issue a to-do is made of.

    Beyond the two fields that drive the checkbox (title and state) an issue
    carries the context that makes a to-do worth having on a board at all: who
    it belongs to, what it is filed under, and whether anyone is talking about
    it. Those are read-only here — the board mirrors them, never writes them.
    """

    number: int
    title: str
    state: str  # "open" | "closed"
    html_url: str
    labels: tuple[str, ...] = ()
    assignee: str | None = None
    comments: int = 0


def issue_from_payload(data: dict) -> Issue:
    """Build an Issue from any GitHub payload carrying one — listing or webhook."""
    assignees = data.get("assignees") or []
    assignee = data.get("assignee") or (assignees[0] if assignees else None)
    return Issue(
        number=data["number"],
        title=data.get("title") or "",
        state=data.get("state") or "open",
        html_url=data.get("html_url") or "",
        # A label is a string in some payloads and an object in others; both
        # forms turn up depending on which endpoint (or webhook) produced it.
        labels=tuple(
            label if isinstance(label, str) else (label.get("name") or "")
            for label in (data.get("labels") or ())
        ),
        assignee=(assignee or {}).get("login") if isinstance(assignee, dict) else assignee,
        comments=int(data.get("comments") or 0),
    )


async def list_issues(
    repo: str,
    *,
    state: str = "all",
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[int, Issue]:
    """Map issue number -> Issue for the repo's issues.

    Pull requests are filtered out: this endpoint returns them alongside issues,
    and a PR sharing a number with a to-do would otherwise drive its state.

    Pages until the repo runs out or ``_ISSUE_MAX_PAGES`` is reached — a
    to-do bound to issue #3 of a repo with four hundred of them was being
    reported with whatever state it happened to have, because the first page
    is the newest hundred and #3 is not in it. Paging stops early on a short
    page, so the common repo still costs exactly one request.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    issues: dict[int, Issue] = {}
    try:
        for page in range(1, _ISSUE_MAX_PAGES + 1):
            resp = await client.get(
                f"/repos/{full_name}/issues",
                params={
                    "state": state,
                    "per_page": _ISSUE_PAGE_SIZE,
                    "page": page,
                },
                headers=_headers(token),
            )
            if resp.status_code == 404:
                return issues
            if resp.status_code == 403:
                raise GitHubError("GitHub rate limit or access denied", status_code=403)
            resp.raise_for_status()
            batch = resp.json()
            issues.update(
                {
                    entry["number"]: issue_from_payload(entry)
                    for entry in batch
                    if "pull_request" not in entry
                }
            )
            if len(batch) < _ISSUE_PAGE_SIZE:
                break
        return issues
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


@dataclass(frozen=True)
class PullRequest:
    """An open pull request, as a tile shows it."""

    number: int
    title: str
    html_url: str
    author: str | None = None
    draft: bool = False
    updated_at: str | None = None


def _pull(data: dict) -> PullRequest:
    return PullRequest(
        number=data["number"],
        title=data.get("title") or "",
        html_url=data.get("html_url") or "",
        author=(data.get("user") or {}).get("login"),
        draft=bool(data.get("draft")),
        updated_at=data.get("updated_at"),
    )


async def list_pulls(
    repo: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[PullRequest]:
    """Open pull requests, newest activity first.

    A repo with no pull requests, or one we cannot see, comes back empty rather
    than as an error: this decorates a tile, and a tile is still a tile without
    it.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/pulls",
            params={
                "state": "open",
                "sort": "updated",
                "direction": "desc",
                "per_page": _PULL_PAGE_SIZE,
            },
            headers=_headers(token),
        )
        if resp.status_code == 404:
            return []
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        return [_pull(entry) for entry in resp.json()]
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
        return issue_from_payload(resp.json())
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
        return issue_from_payload(resp.json())
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


def clear_cache() -> None:
    """Test helper to reset the in-memory cache."""
    _cache.clear()


# --- Git Data API --------------------------------------------------------
#
# The Contents API commits one file at a time, which is the right shape for
# syncing a single IDEA.md but the wrong one for publishing a board: twenty
# tiles would mean twenty commits, and a failure halfway leaves the repo in a
# state that is neither the old board nor the new one. Building a tree instead
# makes a publish one commit that either lands or doesn't.

FILE_MODE = "100644"


def _error_detail(resp: httpx.Response) -> str:
    """GitHub's own explanation for a rejected write, if it gave one."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    parts = [body.get("message", "")]
    parts += [e.get("message", "") for e in body.get("errors", ()) if isinstance(e, dict)]
    return "; ".join(p for p in parts if p)


async def get_tree(
    repo: str,
    ref: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    """Map every file path in a commit's tree to its blob sha, recursively.

    One request answers "what does the board look like right now?", so a publish
    can write only what actually changed without fetching a single file.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=30.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/git/trees/{ref}",
            params={"recursive": "1"},
            headers=_headers(token),
        )
        if resp.status_code == 404:
            return {}
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        data = resp.json()
        if data.get("truncated"):
            # A truncated listing would make the diff below look like a pile of
            # deletions, so refuse rather than publish from a partial picture.
            raise GitHubError("Repository tree too large to publish into")
        return {
            entry["path"]: entry["sha"]
            for entry in data.get("tree", ())
            if entry.get("type") == "blob"
        }
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def get_ref(
    repo: str,
    branch: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Commit sha a branch points at, or None if the branch doesn't exist yet.

    None is the ordinary state of a freshly created repo, not an error.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            f"/repos/{full_name}/git/ref/heads/{branch}", headers=_headers(token)
        )
        if resp.status_code in (404, 409):  # 409 = repo exists but is empty
            return None
        if resp.status_code == 403:
            raise GitHubError("GitHub rate limit or access denied", status_code=403)
        resp.raise_for_status()
        return resp.json()["object"]["sha"]
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def _post(
    repo: str,
    path: str,
    body: dict,
    *,
    token: str | None,
    client: httpx.AsyncClient | None,
    method: str = "POST",
) -> dict:
    """POST/PATCH to a git data endpoint, mapping failures the way callers expect."""
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=30.0)
    try:
        resp = await client.request(
            method, f"/repos/{full_name}{path}", headers=_headers(token), json=body
        )
        if resp.status_code in (401, 403):
            raise GitHubError("GitHub token lacks write access", status_code=403)
        if resp.status_code == 404:
            raise GitHubError("Repository not found or no write access", status_code=404)
        if resp.status_code in (409, 422):
            # 409 and 422 cover everything from a moved ref to a repo with no
            # commits, so GitHub's own wording goes through rather than a guess
            # at which one it was — a wrong guess sends people hunting a
            # conflict that never happened.
            raise GitHubError(
                _error_detail(resp) or "Board changed on GitHub since last publish",
                status_code=409,
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def create_blob(
    repo: str,
    content: bytes,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Upload one file's bytes and return its blob sha, committing nothing."""
    data = await _post(
        repo,
        "/git/blobs",
        {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        token=token,
        client=client,
    )
    return data["sha"]


async def create_tree(
    repo: str,
    entries: list[dict],
    *,
    base_tree: str | None = None,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Build a tree from ``entries`` layered over ``base_tree``.

    An entry with a null sha removes that path, which is how a tile that left
    the board takes its directory with it — git has no empty directories, so
    removing every file under one is the same as removing the directory.
    """
    body: dict = {"tree": entries}
    if base_tree:
        body["base_tree"] = base_tree
    data = await _post(repo, "/git/trees", body, token=token, client=client)
    return data["sha"]


async def create_commit(
    repo: str,
    message: str,
    tree: str,
    parents: list[str],
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    data = await _post(
        repo,
        "/git/commits",
        {"message": message, "tree": tree, "parents": parents},
        token=token,
        client=client,
    )
    return data["sha"]


async def update_ref(
    repo: str,
    branch: str,
    sha: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Move a branch to a commit.

    Never forced: a rejected fast-forward means someone else moved the branch,
    and overwriting that is precisely the data loss this is meant to avoid.
    """
    await _post(
        repo,
        f"/git/refs/heads/{branch}",
        {"sha": sha, "force": False},
        token=token,
        client=client,
        method="PATCH",
    )


# --- Account and repo creation ------------------------------------------
#
# Used once, when a board is first given somewhere to live.


async def whoami(
    token: str, *, client: httpx.AsyncClient | None = None
) -> tuple[str, set[str]]:
    """The token's own login and the scopes it was actually granted.

    Scopes are read from the response header rather than assumed, because a
    token minted before the app asked for ``read:org`` keeps the scopes it had:
    the only way to know what an existing login can do is to ask.
    """
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get("/user", headers=_headers(token))
        if resp.status_code in (401, 403):
            raise GitHubError("GitHub token is not valid", status_code=403)
        resp.raise_for_status()
        granted = {
            s.strip()
            for s in resp.headers.get("X-OAuth-Scopes", "").split(",")
            if s.strip()
        }
        return resp.json()["login"], granted
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def list_orgs(
    token: str, *, client: httpx.AsyncClient | None = None
) -> list[str]:
    """Organisations the token can see. Empty without the ``read:org`` scope."""
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=10.0)
    try:
        resp = await client.get(
            "/user/orgs", params={"per_page": 100}, headers=_headers(token)
        )
        if resp.status_code in (401, 403):
            return []
        resp.raise_for_status()
        return [org["login"] for org in resp.json()]
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def create_repo(
    name: str,
    *,
    org: str | None = None,
    private: bool = True,
    description: str | None = None,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Create a repo under the user or an org. Returns (full_name, default_branch).

    Initialised on creation, because GitHub rejects every git data write to a
    repo with no commits at all — ``POST /git/blobs`` answers "Git Repository is
    empty", so a board could never build its first tree in one. Letting GitHub
    make the first commit is what the web UI does, and it leaves the board's own
    first publish as a single commit on top.
    """
    path = f"/orgs/{org}/repos" if org else "/user/repos"
    body: dict = {"name": name, "private": private, "auto_init": True}
    if description:
        body["description"] = description
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=15.0)
    try:
        resp = await client.post(path, headers=_headers(token), json=body)
        if resp.status_code == 422:
            detail = ""
            try:
                detail = "; ".join(
                    e.get("message", "") for e in resp.json().get("errors", ())
                )
            except ValueError:
                pass
            raise GitHubError(
                detail or f"A repository named {name!r} already exists", status_code=422
            )
        if resp.status_code in (401, 403):
            raise GitHubError(
                "GitHub token cannot create repositories here", status_code=403
            )
        if resp.status_code == 404:
            raise GitHubError(
                f"Organisation {org!r} not found or not accessible", status_code=404
            )
        resp.raise_for_status()
        data = resp.json()
        return data["full_name"], data.get("default_branch") or "main"
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()


async def delete_repo(
    repo: str,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Delete a repository. Needs the ``delete_repo`` scope, which the app never asks for.

    Nothing in the product calls this: it exists for the live GitHub test
    (``backend/tests/live``), which creates a throwaway repo and has to be able
    to take it away again. A test that leaves debris behind stops being run.
    """
    full_name = normalize_repo(repo)
    owned_client = client is None
    client = client or httpx.AsyncClient(base_url=settings.github_api_base, timeout=15.0)
    try:
        resp = await client.delete(f"/repos/{full_name}", headers=_headers(token))
        if resp.status_code == 404:
            return
        if resp.status_code in (401, 403):
            raise GitHubError(
                "GitHub token lacks the delete_repo scope", status_code=403
            )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc
    finally:
        if owned_client:
            await client.aclose()
