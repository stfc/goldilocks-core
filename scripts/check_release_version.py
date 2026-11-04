#!/usr/bin/env python3
"""Fail when the Python package and the Workbench library declare different versions.

The wheel bundles the Workbench frontend that embedders also install as the
goldilocks-workbench library, so one version names both (#239). With --tag,
also fail when a release tag names another version.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def declared_versions() -> dict[str, str]:
    """Return the version each package manifest and lock file declares."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    name = pyproject["project"]["name"]
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package_json = json.loads((ROOT / "web" / "package.json").read_text())
    package_lock = json.loads((ROOT / "web" / "package-lock.json").read_text())
    return {
        "pyproject.toml": pyproject["project"]["version"],
        "uv.lock": next(
            package["version"]
            for package in uv_lock["package"]
            if package["name"] == name
        ),
        "web/package.json": package_json["version"],
        "web/package-lock.json": package_lock["version"],
        'web/package-lock.json packages[""]': package_lock["packages"][""]["version"],
    }


def main() -> int:
    """Compare the declared versions with each other and with an optional tag."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="release tag, such as v0.3.0")
    args = parser.parse_args()

    versions = declared_versions()
    if args.tag is not None:
        versions[f"tag {args.tag}"] = args.tag.removeprefix("v")
    if len(set(versions.values())) == 1:
        print(f"Release version: {versions['pyproject.toml']}")
        return 0
    for source, version in versions.items():
        print(f"{source}: {version}")
    print("::error::the release versions above disagree")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
