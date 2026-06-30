import pytest


async def _create_third_user(email: str) -> int:
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as s:
        u = User(email=email, name=email.split("@")[0])
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


@pytest.mark.asyncio
async def test_invite_existing_user_shows_on_their_board(users, make_client):
    async with make_client(users["a"]) as ca:
        idea_id = (await ca.post("/api/ideas", json={"title": "Shared"})).json()["id"]
        r = await ca.post(
            f"/api/ideas/{idea_id}/collaborators",
            json={"email": "b@example.com", "role": "editor"},
        )
        assert r.status_code == 201
        assert r.json()["status"] == "active"
        assert r.json()["role"] == "editor"

    # B now sees it on their board, marked as shared with owner info
    async with make_client(users["b"]) as cb:
        board = (await cb.get("/api/ideas")).json()
        assert len(board) == 1
        assert board[0]["shared"] is True
        assert board[0]["role"] == "editor"
        assert board[0]["owner"]["email"] == "a@example.com"

    # A's own board shows the idea flagged as having collaborators
    async with make_client(users["a"]) as ca:
        mine = (await ca.get("/api/ideas")).json()
        assert mine[0]["has_collaborators"] is True


@pytest.mark.asyncio
async def test_editor_can_edit_viewer_cannot(users, make_client):
    cid = await _create_third_user("c@example.com")
    async with make_client(users["a"]) as ca:
        idea_id = (await ca.post("/api/ideas", json={"title": "Roles"})).json()["id"]
        await ca.post(
            f"/api/ideas/{idea_id}/collaborators",
            json={"email": "b@example.com", "role": "editor"},
        )
        await ca.post(
            f"/api/ideas/{idea_id}/collaborators",
            json={"email": "c@example.com", "role": "viewer"},
        )

    # editor B can edit + add todos
    async with make_client(users["b"]) as cb:
        assert (await cb.patch(f"/api/ideas/{idea_id}", json={"progress": 30})).status_code == 200
        assert (
            await cb.post(f"/api/ideas/{idea_id}/todos", json={"text": "x"})
        ).status_code == 201
        # editor cannot delete the idea (owner only)
        assert (await cb.delete(f"/api/ideas/{idea_id}")).status_code == 403

    # viewer C can read but not edit
    async with make_client(cid) as cc:
        assert (await cc.get(f"/api/ideas/{idea_id}")).status_code == 200
        assert (await cc.patch(f"/api/ideas/{idea_id}", json={"progress": 1})).status_code == 403
        assert (
            await cc.post(f"/api/ideas/{idea_id}/todos", json={"text": "no"})
        ).status_code == 403


@pytest.mark.asyncio
async def test_pending_invite_claimed_on_login(users, make_client, anon_client):
    # A invites an email with no account yet
    async with make_client(users["a"]) as ca:
        idea_id = (await ca.post("/api/ideas", json={"title": "Future"})).json()["id"]
        r = await ca.post(
            f"/api/ideas/{idea_id}/collaborators",
            json={"email": "newbie@example.com", "role": "editor"},
        )
        assert r.json()["status"] == "pending"
        listing = (await ca.get(f"/api/ideas/{idea_id}/collaborators")).json()
        assert any(c["status"] == "pending" and c["email"] == "newbie@example.com" for c in listing)

    # Simulate that person registering with the matching email, then it auto-activates.
    from app.auth import login_with_identity
    from app.db import SessionLocal

    async with SessionLocal() as s:
        user = await login_with_identity(
            s,
            provider="google",
            subject="newbie-sub",
            email="newbie@example.com",
            email_verified=True,
            name="Newbie",
        )
        newbie_id = user.id

    async with make_client(newbie_id) as cn:
        board = (await cn.get("/api/ideas")).json()
        assert len(board) == 1
        assert board[0]["id"] == idea_id
        assert board[0]["role"] == "editor"

    # the pending invite is gone
    async with make_client(users["a"]) as ca:
        listing = (await ca.get(f"/api/ideas/{idea_id}/collaborators")).json()
        assert not any(c["status"] == "pending" for c in listing)
        assert any(c["email"] == "newbie@example.com" and c["status"] == "active" for c in listing)


@pytest.mark.asyncio
async def test_non_member_cannot_see_idea(users, make_client):
    cid = await _create_third_user("c@example.com")
    async with make_client(users["a"]) as ca:
        idea_id = (await ca.post("/api/ideas", json={"title": "Private"})).json()["id"]
    async with make_client(cid) as cc:
        assert (await cc.get(f"/api/ideas/{idea_id}")).status_code == 404
        assert (await cc.get("/api/ideas")).json() == []


@pytest.mark.asyncio
async def test_collaborator_can_leave(users, make_client):
    async with make_client(users["a"]) as ca:
        idea_id = (await ca.post("/api/ideas", json={"title": "Leave me"})).json()["id"]
        await ca.post(
            f"/api/ideas/{idea_id}/collaborators",
            json={"email": "b@example.com", "role": "editor"},
        )
    async with make_client(users["b"]) as cb:
        # B removes themselves
        assert (
            await cb.delete(f"/api/ideas/{idea_id}/collaborators/{users['b']}")
        ).status_code == 204
        assert (await cb.get("/api/ideas")).json() == []
