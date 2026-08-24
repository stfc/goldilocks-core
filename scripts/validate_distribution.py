#!/usr/bin/env python3
"""Validate runtime files and metadata in built Python distributions."""

from __future__ import annotations

import argparse
import tarfile
import tomllib
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

_REQUIRED_PACKAGE_FILES = (
    "goldilocks_core/ml/registry.toml",
    "goldilocks_core/pseudo/registry.toml",
    "goldilocks_core/examples/structures/README.md",
    "goldilocks_core/examples/structures/Si.cif",
    "goldilocks_core/examples/structures/Fe_bcc.cif",
    "goldilocks_core/examples/structures/Pt_fcc.cif",
)
_FORBIDDEN_PARTS = frozenset(
    {
        ".agents",
        ".github",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "docs",
        "mutants",
        "node_modules",
        "scripts",
        "tests",
        "web",
    }
)
_FORBIDDEN_SUFFIXES = (".joblib", ".pt", ".pth", ".upf")


def main() -> int:
    """Check one wheel and one source archive at the distribution seam."""
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["project"]
    wheels = tuple(args.dist_dir.glob("*.whl"))
    source_archives = tuple(args.dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1:
        parser.error(f"expected one wheel, found {len(wheels)}")
    if len(source_archives) != 1:
        parser.error(f"expected one source archive, found {len(source_archives)}")

    with ZipFile(wheels[0]) as wheel:
        wheel_names = tuple(wheel.namelist())
        _require_package_files(parser, wheel_names, "wheel")
        _reject_development_files(parser, wheel_names, "wheel")
        metadata_name = _one_matching(wheel_names, ".dist-info/METADATA", parser)
        entry_points_name = _one_matching(
            wheel_names, ".dist-info/entry_points.txt", parser
        )
        _validate_metadata(parser, wheel.read(metadata_name), project)
        entry_points = wheel.read(entry_points_name).decode("utf-8")
        if entry_points != (
            "[console_scripts]\ngoldilocks = goldilocks_core.cli.core:main\n"
        ):
            parser.error("wheel console entry point differs from canonical CLI")

    with tarfile.open(source_archives[0], mode="r:gz") as source_archive:
        source_names = tuple(source_archive.getnames())
    package_names = tuple(
        name.split("/src/", 1)[1] for name in source_names if "/src/" in name
    )
    _require_package_files(parser, package_names, "source archive")
    _reject_development_files(parser, source_names, "source archive")

    print(
        f"Validated {len(_REQUIRED_PACKAGE_FILES)} runtime files, metadata, "
        f"entry point, and exclusions in {wheels[0]} and {source_archives[0]}"
    )
    return 0


def _require_package_files(
    parser: argparse.ArgumentParser, names: tuple[str, ...], label: str
) -> None:
    missing = [name for name in _REQUIRED_PACKAGE_FILES if name not in names]
    if missing:
        parser.error(f"{label} does not contain {', '.join(missing)}")


def _reject_development_files(
    parser: argparse.ArgumentParser, names: tuple[str, ...], label: str
) -> None:
    forbidden = [
        name
        for name in names
        if _FORBIDDEN_PARTS.intersection(PurePosixPath(name).parts)
        or name.lower().endswith(_FORBIDDEN_SUFFIXES)
        or "__pycache__" in PurePosixPath(name).parts
        or name.endswith((".pyc", ".coverage"))
    ]
    if forbidden:
        parser.error(
            f"{label} contains development or runtime asset file {forbidden[0]}"
        )


def _one_matching(
    names: tuple[str, ...], suffix: str, parser: argparse.ArgumentParser
) -> str:
    matches = tuple(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        parser.error(f"expected one {suffix}, found {len(matches)}")
    return matches[0]


def _validate_metadata(
    parser: argparse.ArgumentParser, content: bytes, project: dict
) -> None:
    metadata = BytesParser().parsebytes(content)
    expected = {
        "Name": project["name"],
        "Version": project["version"],
        "Requires-Python": project["requires-python"],
    }
    for field, value in expected.items():
        if metadata[field] != value:
            parser.error(f"wheel metadata has the wrong {field}")
    extras = set(metadata.get_all("Provides-Extra", ()))
    expected_extras = set(project.get("optional-dependencies", ()))
    if extras != expected_extras:
        parser.error(f"wheel metadata has unexpected extras: {sorted(extras)}")


if __name__ == "__main__":
    raise SystemExit(main())
