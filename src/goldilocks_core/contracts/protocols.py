from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from pymatgen.core import Structure

from goldilocks_core.contracts.kpoints import KPointSelection
from goldilocks_core.contracts.models import ModelPrediction

KMeshAdvisor = Callable[[Structure], KPointSelection]


@runtime_checkable
class KMeshService(Protocol):
    def __call__(self, structure: Structure) -> KPointSelection: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class StructureModel(Protocol):
    """A loaded model: structure in, prediction out.

    Core calls only ``predict``; feature extraction and estimator internals
    stay on the model-providing side of this seam, so a package satisfying
    this protocol structurally never needs to import Core.
    """

    def predict(self, structure: Structure) -> ModelPrediction: ...


PredictionResolver = Callable[[Structure, ModelPrediction], object]
"""Turns a model's prediction into the parameter's advice or selection type.

Looked up in ``PREDICTION_RESOLVERS`` by ``ModelPrediction.parameter``, so
routing a prediction is a lookup, never a branch per model.
"""

PREDICTION_RESOLVERS: dict[str, PredictionResolver] = {}
