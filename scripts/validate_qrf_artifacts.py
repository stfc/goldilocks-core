#!/usr/bin/env python3
"""Run the opt-in real-artifact QRF compatibility check."""

from __future__ import annotations

import argparse
import json

from goldilocks_core.ml.validation import validate_real_qrf_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="explicitly allow resolving and loading the packaged remote artifacts",
    )
    parser.add_argument("--registry", help="optional model registry path")
    args = parser.parse_args()
    if not args.allow_network:
        parser.error("--allow-network is required for real artifact validation")

    result = validate_real_qrf_artifacts(
        allow_network=args.allow_network,
        registry_path=args.registry,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
