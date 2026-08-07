"""Callable stage signatures for the Core recommendation pipeline."""

from __future__ import annotations

from typing import Callable

from pymatgen.core import Structure

from goldilocks_core.contracts.records import KPointSelection

KMeshAdvisor = Callable[[Structure], KPointSelection]
"""Kmesh-stage backend signature: predict a k-point mesh from a structure."""
