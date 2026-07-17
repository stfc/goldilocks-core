#!/usr/bin/env python3
"""Validate required files in built source and wheel distributions."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path
from zipfile import ZipFile

_REQUIRED_PACKAGE_FILE = "goldilocks_core/model_registry.toml"


def main() -> int:
    """Check that one wheel and one source archive contain package data."""
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    wheels = tuple(args.dist_dir.glob("*.whl"))
    source_archives = tuple(args.dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1:
        parser.error(f"expected one wheel, found {len(wheels)}")
    if len(source_archives) != 1:
        parser.error(f"expected one source archive, found {len(source_archives)}")

    with ZipFile(wheels[0]) as wheel:
        if _REQUIRED_PACKAGE_FILE not in wheel.namelist():
            parser.error(f"wheel does not contain {_REQUIRED_PACKAGE_FILE}")

    with tarfile.open(source_archives[0], mode="r:gz") as source_archive:
        members = source_archive.getnames()
        suffix = f"/src/{_REQUIRED_PACKAGE_FILE}"
        if not any(member.endswith(suffix) for member in members):
            parser.error(f"source archive does not contain {_REQUIRED_PACKAGE_FILE}")

    print(f"Validated {wheels[0]} and {source_archives[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
