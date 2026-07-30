import httpx
import pytest
import respx

from app import github
from app.github import GitHubError, fetch_repo, normalize_repo


def test_normalize_repo():
    assert normalize_repo("owner/name") == "owner/name"
    assert normalize_repo("https://github.com/owner/name") == "owner/name"
    assert normalize_repo("https://github.com/owner/name.git") == "owner/name"
    assert normalize_repo("git@github.com:owner/name.git") == "owner/name"
    with pytest.raises(GitHubError):
        normalize_repo("not a repo")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repo_mocked():
    github.clear_cache()
    base = "https://api.github.com"
    respx.get(f"{base}/repos/octocat/hello").mock(
        return_value=httpx.Response(
            200,
            json={
                "full_name": "octocat/hello",
                "html_url": "https://github.com/octocat/hello",
                "description": "greetings",
                "stargazers_count": 42,
                "open_issues_count": 3,
                "forks_count": 7,
                "language": "Python",
                "default_branch": "main",
                "pushed_at": "2026-06-01T00:00:00Z",
            },
        )
    )
    respx.get(f"{base}/repos/octocat/hello/commits").mock(
        return_value=httpx.Response(
            200, json=[{"commit": {"message": "latest commit\n\nbody"}}]
        )
    )

    repo = await fetch_repo("octocat/hello")
    assert repo.stars == 42
    assert repo.open_issues == 3
    assert repo.language == "Python"
    assert repo.last_commit_message == "latest commit"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_repo_not_found():
    github.clear_cache()
    respx.get("https://api.github.com/repos/no/such").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(GitHubError) as exc:
        await fetch_repo("no/such")
    assert exc.value.status_code == 404


def test_schema_normalizes_repo_on_write():
    """Repos are stored as owner/name — the UI builds hrefs from the raw value."""
    from app.schemas import IdeaCreate, IdeaUpdate

    assert (
        IdeaCreate(title="t", github_repo="https://github.com/o/n.git").github_repo
        == "o/n"
    )
    assert IdeaCreate(title="t", github_repo="git@github.com:o/n.git").github_repo == "o/n"
    assert IdeaCreate(title="t", github_repo="o/n").github_repo == "o/n"
    assert IdeaUpdate(github_repo="https://github.com/o/n/").github_repo == "o/n"
    # Blank means "unlinked", not a repo named "".
    assert IdeaCreate(title="t", github_repo="  ").github_repo is None
    with pytest.raises(ValueError):
        IdeaCreate(title="t", github_repo="not a repo")


@pytest.mark.asyncio
@respx.mock
async def test_create_idea_stores_normalized_repo(users, make_client):
    # Creating a repo-linked idea tries to adopt its IDEA.md and logo; keep
    # both offline.
    respx.get(
        "https://api.github.com/repos/octocat/hello/contents/IDEA.md"
    ).mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    respx.get("https://api.github.com/repos/octocat/hello/contents/").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = make_client(users["a"])
    resp = await client.post(
        "/api/ideas",
        json={"title": "Linked", "github_repo": "https://github.com/octocat/hello.git"},
    )
    assert resp.status_code == 201
    assert resp.json()["github_repo"] == "octocat/hello"
