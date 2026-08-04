#!/usr/bin/env python3
"""Validate required files in built source and wheel distributions."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path
from zipfile import ZipFile

_REQUIRED_PACKAGE_FILES = (
    "goldilocks_core/model_registry.toml",
    "goldilocks_core/examples/structures/Si.cif",
    "goldilocks_core/examples/structures/Fe_bcc.cif",
    "goldilocks_core/examples/structures/Pt_fcc.cif",
)


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
        wheel_names = set(wheel.namelist())
    missing_from_wheel = [
        name for name in _REQUIRED_PACKAGE_FILES if name not in wheel_names
    ]
    if missing_from_wheel:
        parser.error(f"wheel does not contain {', '.join(missing_from_wheel)}")

    with tarfile.open(source_archives[0], mode="r:gz") as source_archive:
        members = source_archive.getnames()
    missing_from_source = [
        name
        for name in _REQUIRED_PACKAGE_FILES
        if not any(member.endswith(f"/src/{name}") for member in members)
    ]
    if missing_from_source:
        parser.error(
            f"source archive does not contain {', '.join(missing_from_source)}"
        )

    print(
        f"Validated {len(_REQUIRED_PACKAGE_FILES)} packaged files in "
        f"{wheels[0]} and {source_archives[0]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
