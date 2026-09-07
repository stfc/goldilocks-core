from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    PREDICTION_RESOLVERS,
    KMeshAdvisor,
    KMeshEntry,
    KPointSelection,
    ModelSpec,
    Provenance,
)
from goldilocks_core.kmesh.math import (
    build_kmesh_entries,
    generate_candidate_k_distances,
)

if TYPE_CHECKING:
    from goldilocks_ml.inference import ModelPrediction


def _select_kmesh_entry(
    entries: list[KMeshEntry],
    predicted_k_index: float,
) -> KMeshEntry:
    target_index = max(1, math.ceil(predicted_k_index))
    max_k_index = entries[-1].k_index
    target_index = min(target_index, max_k_index)

    # k_index is 1-based; the list is not.
    return entries[target_index - 1]


def _resolve_k_points_prediction(
    structure: Structure, prediction: ModelPrediction
) -> KPointSelection:
    """Turn goldilocks-ml's k_index prediction into a concrete mesh.

    ``prediction.value`` is a rung on this same ladder -- rung 1 is the
    Gamma-only mesh -- by contract, not by convention Core has to guess or
    translate. There is exactly one k_index numbering in this system; a
    model publishing anything else is a contract violation, not a case to
    handle here.
    """
    candidate_distances = generate_candidate_k_distances(structure)
    entries = build_kmesh_entries(structure, candidate_distances)
    selected_entry = _select_kmesh_entry(entries, float(prediction.value))

    return KPointSelection(
        mesh_type="monkhorst-pack",
        grid=selected_entry.mesh,
        shift=(0, 0, 0),
        provenance=Provenance(
            source="model",
            reason="Select nearest k-mesh entry from predicted k-index.",
            data_source=prediction.model_id,
            confidence=prediction.confidence,
            details=prediction.details,
            warnings=prediction.warnings,
        ),
    )


PREDICTION_RESOLVERS["k_points"] = _resolve_k_points_prediction


def ml_kmesh_advisor(spec: ModelSpec) -> KMeshAdvisor:
    def advisor(structure: Structure) -> KPointSelection:
        return advise_kpoints(structure, spec)

    return advisor


def advise_kpoints(
    structure: Structure,
    spec: ModelSpec,
) -> KPointSelection:
    """``spec.location`` names a directory holding a goldilocks-ml model
    record (``model.json`` beside its estimator), same shape as any other
    model this runtime loads -- not a single joblib file."""
    from goldilocks_ml.inference import load_model

    model = load_model(Path(spec.location))
    prediction = model.predict(structure)
    resolver = PREDICTION_RESOLVERS[prediction.parameter]
    return resolver(structure, prediction)
