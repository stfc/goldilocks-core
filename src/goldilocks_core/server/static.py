"""Serve the built Workbench application from FastAPI.

The static mount is optional: it activates only when a configured or default
build directory containing ``index.html`` exists, and it is registered after
every API route so it never shadows API/health paths. A catch-all GET returns
``index.html`` for any other path (SPA fallback) and is excluded from OpenAPI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from goldilocks_core.server.config import WEB_DIST_ENV

__all__ = ["DEFAULT_WEB_DIST", "mount_workbench", "resolve_web_dist"]

DEFAULT_WEB_DIST = "web/dist"


def resolve_web_dist(env: Mapping[str, str] | None = None) -> Path | None:
    """Resolve the Workbench build directory, or None if absent.

    Uses ``GOLDILOCKS_WEB_DIST`` when set, else the repository-relative default.
    Returns None unless the directory exists and contains an ``index.html``.
    """
    env = os.environ if env is None else env
    raw = env.get(WEB_DIST_ENV)
    candidate = Path(raw) if raw else Path(DEFAULT_WEB_DIST)
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return candidate
    return None


def mount_workbench(app: Any) -> bool:
    """Serve the Vite build if present; return whether it was mounted.

    Must be called after all API routes are registered so the static fallback
    never shadows them. Only hashed asset files are served from ``/assets``;
    every other GET path returns the SPA shell.
    """
    from fastapi.staticfiles import StaticFiles

    build_dir = resolve_web_dist()
    if build_dir is None:
        return False

    assets = build_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Any:
        from fastapi.responses import FileResponse

        del full_path
        return FileResponse(build_dir / "index.html")

    return True
