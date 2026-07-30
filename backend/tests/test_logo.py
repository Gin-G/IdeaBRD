import base64

import pytest

# Smallest valid PNG (1x1, transparent).
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def _new_idea(client, title="Logo idea") -> int:
    resp = await client.post("/api/ideas", json={"title": title})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_upload_then_serve_logo(users, make_client):
    async with make_client(users["a"]) as c:
        idea_id = await _new_idea(c)

        resp = await c.put(
            f"/api/ideas/{idea_id}/logo",
            files={"file": ("logo.png", PNG, "image/png")},
        )
        assert resp.status_code == 200
        logo_url = resp.json()["logo_url"]
        # Versioned so replacing the image busts a cached copy.
        assert logo_url.startswith(f"/api/ideas/{idea_id}/logo?v=")

        resp = await c.get(f"/api/ideas/{idea_id}/logo")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content == PNG


@pytest.mark.asyncio
async def test_replacing_a_logo_changes_the_version(users, make_client):
    async with make_client(users["a"]) as c:
        idea_id = await _new_idea(c)
        first = (
            await c.put(
                f"/api/ideas/{idea_id}/logo",
                files={"file": ("a.png", PNG, "image/png")},
            )
        ).json()["logo_url"]

        gif = b"GIF89a" + b"\x00" * 20
        resp = await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("b.gif", gif, "image/gif")}
        )
        assert resp.status_code == 200
        assert resp.json()["logo_url"] != first

        served = await c.get(f"/api/ideas/{idea_id}/logo")
        assert served.headers["content-type"] == "image/gif"
        assert served.content == gif


@pytest.mark.asyncio
async def test_rejects_svg_and_oversized_images(users, make_client):
    async with make_client(users["a"]) as c:
        idea_id = await _new_idea(c)

        # SVG can carry script, so it is not an accepted logo format.
        resp = await c.put(
            f"/api/ideas/{idea_id}/logo",
            files={"file": ("x.svg", b"<svg/>", "image/svg+xml")},
        )
        assert resp.status_code == 415

        resp = await c.put(
            f"/api/ideas/{idea_id}/logo",
            files={"file": ("big.png", b"\x00" * (1024 * 1024 + 1), "image/png")},
        )
        assert resp.status_code == 413

        # Nothing was stored by either rejected upload.
        assert (await c.get(f"/api/ideas/{idea_id}/logo")).status_code == 404


@pytest.mark.asyncio
async def test_delete_logo_clears_the_url(users, make_client):
    async with make_client(users["a"]) as c:
        idea_id = await _new_idea(c)
        await c.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )

        resp = await c.delete(f"/api/ideas/{idea_id}/logo")
        assert resp.status_code == 200
        assert resp.json()["logo_url"] is None
        assert (await c.get(f"/api/ideas/{idea_id}/logo")).status_code == 404


@pytest.mark.asyncio
async def test_viewer_can_read_but_not_replace(users, make_client):
    async with make_client(users["a"]) as ca:
        idea_id = await _new_idea(ca, "Shared logo")
        await ca.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )
        await ca.post(
            f"/api/ideas/{idea_id}/collaborators",
            json={"email": "b@example.com", "role": "viewer"},
        )

    async with make_client(users["b"]) as cb:
        assert (await cb.get(f"/api/ideas/{idea_id}/logo")).status_code == 200
        resp = await cb.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )
        assert resp.status_code == 403
        assert (await cb.delete(f"/api/ideas/{idea_id}/logo")).status_code == 403


@pytest.mark.asyncio
async def test_non_member_cannot_see_the_logo(users, make_client):
    async with make_client(users["a"]) as ca:
        idea_id = await _new_idea(ca, "Private")
        await ca.put(
            f"/api/ideas/{idea_id}/logo", files={"file": ("l.png", PNG, "image/png")}
        )

    async with make_client(users["b"]) as cb:
        # 404 rather than 403: don't leak that the idea exists.
        assert (await cb.get(f"/api/ideas/{idea_id}/logo")).status_code == 404
