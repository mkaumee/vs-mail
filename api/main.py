"""The VS-Mail service.

Deploys to Railway, where DEEPSEEK_API_KEY and VS_SERVICE_TOKEN live. The
key exists only in that environment: never in this repository, never in a
commit, never in a log line.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
