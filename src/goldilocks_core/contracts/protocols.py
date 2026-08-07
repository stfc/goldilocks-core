"""Callable stage signatures for the Core recommendation pipeline."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from pymatgen.core import Structure

from goldilocks_core.contracts.records import KPointSelection

KMeshAdvisor = Callable[[Structure], KPointSelection]
"""Kmesh-stage backend signature: predict a k-point mesh from a structure."""


@runtime_checkable
class ModelRuntime(Protocol):
    """Lifecycle owner for loaded ML model resources.

    Implementations own model load/reuse/reset/close so that long-lived
    processes can discard or release cached models without module globals.
    """

    def reset(self) -> None: ...
    def close(self) -> None: ...
