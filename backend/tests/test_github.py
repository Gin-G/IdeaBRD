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
