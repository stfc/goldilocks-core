from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = ["available_structures", "structure", "structures_path"]


def structures_path() -> Path:
    return Path(resources.files("goldilocks_core.examples") / "structures")


def available_structures() -> tuple[str, ...]:
    return tuple(sorted(path.name for path in structures_path().glob("*.cif")))


def structure(name: str) -> Path:
    path = structures_path() / name
    if not path.is_file():
        available = ", ".join(available_structures())
        raise FileNotFoundError(
            f"Unknown example structure {name!r}; available: {available}"
        )
    return path
