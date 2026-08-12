"""Callable stage signatures for the Core recommendation pipeline."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from pymatgen.core import Structure

from goldilocks_core.contracts.records import KPointSelection

KMeshAdvisor = Callable[[Structure], KPointSelection]
"""Kmesh-stage advisor signature: predict a k-point mesh from a structure."""


@runtime_checkable
class KMeshService(Protocol):
    """Runtime-owned kmesh service: callable plus ``reset``/``close``."""

    def __call__(self, structure: Structure) -> KPointSelection: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...
