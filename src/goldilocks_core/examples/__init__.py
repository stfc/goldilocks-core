"""Example crystal structures shipped with goldilocks-core.

The structures are installed with the package so that a `pip install` is enough
to run the pipeline end to end, without cloning the repository.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = ["available_structures", "structure", "structures_path"]


def structures_path() -> Path:
    """Return the directory holding the bundled example structures."""
    return Path(resources.files("goldilocks_core.examples") / "structures")


def available_structures() -> tuple[str, ...]:
    """Return the filenames of every bundled example structure."""
    return tuple(sorted(path.name for path in structures_path().glob("*.cif")))


def structure(name: str) -> Path:
    """Return the path to one bundled example structure.

    Raises
    ------
    FileNotFoundError
        If no bundled structure has that filename.
    """
    path = structures_path() / name
    if not path.is_file():
        available = ", ".join(available_structures())
        raise FileNotFoundError(
            f"Unknown example structure {name!r}; available: {available}"
        )
    return path
