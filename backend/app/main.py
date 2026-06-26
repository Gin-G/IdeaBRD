from __future__ import annotations

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocketDisconnect

from app.auth import SESSION_USER_KEY
from app.config import settings
from app.realtime import manager
from app.routers import auth, collaborators, ideas, repos, todos

app = FastAPI(title="IdeaBRD API", version="0.1.0")

# Signed, httpOnly session cookie (holds only the user id).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.cookie_secure,
    same_site="lax",
)

# In dev the SPA runs on a different origin (Vite) and needs credentialed CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ideas.router)
app.include_router(todos.router)
app.include_router(repos.router)
app.include_router(collaborators.router)


@app.get("/api/health", tags=["meta"])
async def health():
    return {"status": "ok", "auth": "google" if settings.auth_enabled else "dev"}


@app.websocket("/api/ws")
async def ws(websocket: WebSocket):
    """Live-update channel. Authenticated via the session cookie (same-origin)."""
    user_id = websocket.session.get(SESSION_USER_KEY)
    if not user_id:
        await websocket.close(code=1008)
        return
    await manager.connect(user_id, websocket)
    try:
        while True:
            # We don't expect client messages; this keeps the socket open.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
