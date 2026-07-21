#!/usr/bin/env python3
"""Fail when exported mutmut results fall below the required mutation score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """Read mutmut CI statistics and enforce a killed-mutant ratio."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stats", type=Path)
    parser.add_argument("--minimum", type=float, default=0.75)
    args = parser.parse_args()

    stats = json.loads(args.stats.read_text())
    killed = int(stats["killed"])
    total = int(stats["total"])
    if total <= 0:
        parser.error("mutation statistics contain no mutants")
    if not 0.0 <= args.minimum <= 1.0:
        parser.error("--minimum must be between 0 and 1")

    score = killed / total
    print(f"Mutation score: {killed}/{total} ({score:.1%}); minimum {args.minimum:.1%}")
    return int(score < args.minimum)


if __name__ == "__main__":
    raise SystemExit(main())
