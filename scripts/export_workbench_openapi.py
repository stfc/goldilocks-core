from __future__ import annotations

import argparse
import json
from pathlib import Path

from goldilocks_core.runtime import Service
from goldilocks_core.server.http import create_app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the typed HTTP contract used by Goldilocks Workbench."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix != ".json":
        parser.error("--output must name a JSON file")
    output.parent.mkdir(parents=True, exist_ok=True)

    service = Service()
    try:
        schema = create_app(service).openapi()
    finally:
        service.close()

    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(output)


if __name__ == "__main__":
    main()
