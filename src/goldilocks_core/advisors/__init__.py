"""Advisor interfaces for calculation recommendations."""

from __future__ import annotations

from typing import Any

__all__ = ["advise_kpoints", "default_kmesh_advisor", "ml_kmesh_advisor"]


def __getattr__(name: str) -> Any:
    """Load advisor implementations only when their public names are requested."""
    if name == "default_kmesh_advisor":
        from .kdistance_advisor import default_kmesh_advisor

        return default_kmesh_advisor
    if name in {"advise_kpoints", "ml_kmesh_advisor"}:
        from .kindex_advisor import advise_kpoints, ml_kmesh_advisor

        return {
            "advise_kpoints": advise_kpoints,
            "ml_kmesh_advisor": ml_kmesh_advisor,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
