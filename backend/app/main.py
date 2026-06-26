from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import auth, ideas, repos, todos

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


@app.get("/api/health", tags=["meta"])
async def health():
    return {"status": "ok", "auth": "google" if settings.auth_enabled else "dev"}
