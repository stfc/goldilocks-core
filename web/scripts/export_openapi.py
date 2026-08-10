"""Export the FastAPI OpenAPI document that drives generated Workbench types.

Deterministic: builds the app from ``create_app()`` without a running server or
lifespan, then writes ``scripts/openapi.json``. Invoked from ``scripts/api.mjs``
with the repository root as cwd so ``goldilocks-core[http]`` resolves. The
output path is ``scripts/openapi.json`` unless overridden on argv (used by the
verify step to render into a temporary directory).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from goldilocks_core.server.http import create_app

DEFAULT_OUT = Path(__file__).resolve().parent / "openapi.json"


def main() -> None:
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUT
    app = create_app()
    spec = app.openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
