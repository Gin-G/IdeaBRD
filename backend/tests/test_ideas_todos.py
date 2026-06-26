import pytest


@pytest.mark.asyncio
async def test_idea_crud_and_isolation(users, make_client):
    async with make_client(users["a"]) as ca:
        # create
        r = await ca.post("/api/ideas", json={"title": "First idea", "notes": "hi"})
        assert r.status_code == 201
        idea = r.json()
        idea_id = idea["id"]
        assert idea["position"] == 0
        assert idea["todos"] == []

        # list
        r = await ca.get("/api/ideas")
        assert r.status_code == 200
        assert len(r.json()) == 1

        # update
        r = await ca.patch(
            f"/api/ideas/{idea_id}", json={"progress": 50, "status": "active"}
        )
        assert r.status_code == 200
        assert r.json()["progress"] == 50
        assert r.json()["status"] == "active"

    # user B cannot see or touch user A's idea
    async with make_client(users["b"]) as cb:
        assert (await cb.get("/api/ideas")).json() == []
        assert (await cb.get(f"/api/ideas/{idea_id}")).status_code == 404
        assert (await cb.patch(f"/api/ideas/{idea_id}", json={"progress": 1})).status_code == 404
        assert (await cb.delete(f"/api/ideas/{idea_id}")).status_code == 404

    # owner can delete
    async with make_client(users["a"]) as ca:
        assert (await ca.delete(f"/api/ideas/{idea_id}")).status_code == 204
        assert (await ca.get("/api/ideas")).json() == []


@pytest.mark.asyncio
async def test_reorder(users, make_client):
    async with make_client(users["a"]) as ca:
        ids = []
        for t in ["one", "two", "three"]:
            ids.append((await ca.post("/api/ideas", json={"title": t})).json()["id"])

        r = await ca.patch(
            "/api/ideas/reorder",
            json=[
                {"id": ids[0], "position": 2},
                {"id": ids[2], "position": 0},
            ],
        )
        assert r.status_code == 204
        ordered = [i["id"] for i in (await ca.get("/api/ideas")).json()]
        assert ordered[0] == ids[2]
        assert ordered[-1] == ids[0]


@pytest.mark.asyncio
async def test_todos(users, make_client):
    async with make_client(users["a"]) as ca:
        idea_id = (await ca.post("/api/ideas", json={"title": "T"})).json()["id"]

        r = await ca.post(f"/api/ideas/{idea_id}/todos", json={"text": "do thing"})
        assert r.status_code == 201
        todo_id = r.json()["id"]
        assert r.json()["done"] is False

        r = await ca.patch(f"/api/todos/{todo_id}", json={"done": True})
        assert r.status_code == 200
        assert r.json()["done"] is True

        assert len((await ca.get(f"/api/ideas/{idea_id}/todos")).json()) == 1

        assert (await ca.delete(f"/api/todos/{todo_id}")).status_code == 204
        assert (await ca.get(f"/api/ideas/{idea_id}/todos")).json() == []

    # isolation: user B cannot add todos to user A's idea
    async with make_client(users["b"]) as cb:
        assert (
            await cb.post(f"/api/ideas/{idea_id}/todos", json={"text": "x"})
        ).status_code == 404
