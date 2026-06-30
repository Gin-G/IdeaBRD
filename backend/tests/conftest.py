from __future__ import annotations

import os

# Configure the app for tests BEFORE importing it.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_ideabrd.db"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.auth import get_current_user  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


@pytest_asyncio.fixture
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def users(db):
    """Create two users; return their ids."""
    from app.db import SessionLocal

    async with SessionLocal() as s:
        a = User(email="a@example.com", name="A")
        b = User(email="b@example.com", name="B")
        s.add_all([a, b])
        await s.commit()
        await s.refresh(a)
        await s.refresh(b)
        return {"a": a.id, "b": b.id}


def client_as(user_id: int) -> AsyncClient:
    """An HTTP client whose requests are authenticated as the given user."""

    async def override():
        from app.db import SessionLocal

        async with SessionLocal() as s:
            return await s.get(User, user_id)

    app.dependency_overrides[get_current_user] = override
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def make_client():
    yield client_as
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
