"""The VS-Mail service.

Deploys to Railway, where DEEPSEEK_API_KEY and VS_SERVICE_TOKEN live. The
key exists only in that environment: never in this repository, never in a
commit, never in a log line.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.app_routes import app_router, oauth_router
from api.routes import guarded, router

app = FastAPI(
    title="VS-Mail",
    description="Email triage and shipping document verification.",
    version="0.1.0",
)

# The frontend is served from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(guarded)
app.include_router(app_router)
# Unguarded, because Google redirects a browser to it. Registered here with
# the rest so it is ahead of the catch-all that serves the page.
app.include_router(oauth_router)

#: The built frontend, served by this same app so there is one URL, one
#: deploy and no CORS. Mounted last so it cannot shadow an API route.
STATIC = Path(__file__).resolve().parent / "static"

if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        """Anything not an API route is the app; the browser routes it.

        A real file is served if it exists, so favicons and the like work.
        """
        candidate = STATIC / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC / "index.html")
