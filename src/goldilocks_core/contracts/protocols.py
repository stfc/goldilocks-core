from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from pymatgen.core import Structure

from goldilocks_core.contracts.kpoints import KPointSelection

KMeshAdvisor = Callable[[Structure], KPointSelection]


@runtime_checkable
class KMeshService(Protocol):
    def __call__(self, structure: Structure) -> KPointSelection: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...
