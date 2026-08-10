"""Module-level FastAPI application for process servers (uvicorn, Docker).

Exposes a single ``app`` so uvicorn and the container can start the Workbench
transport without constructing a server programmatically. Deployment values are
read from the environment when the module is imported: see
``goldilocks_core.server.config`` and ``goldilocks_core.server.static``.
"""

from __future__ import annotations

from goldilocks_core.server.http import create_app

app = create_app()

__all__ = ["app"]
