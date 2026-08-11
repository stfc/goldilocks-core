"""Kmesh stage backend: resolve k-point hints into a selection, else a model."""

from __future__ import annotations

from .resolve import resolve_kpoints

__all__ = ["resolve_kpoints"]
