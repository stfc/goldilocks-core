"""K-point recommendation utilities."""

from __future__ import annotations

import math

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    KMeshAdvisor,
    KMeshEntry,
    KPointSelection,
    ModelSpec,
    Provenance,
)
from goldilocks_core.kmesh import (
    build_kmesh_entries,
    generate_candidate_k_distances,
    resolve_kpoints_from_advice,
)
from goldilocks_core.ml.features import extract_cslr_features
from goldilocks_core.ml.inference import predict
from goldilocks_core.ml.models import load_model


def _select_kmesh_entry(
    entries: list[KMeshEntry],
    predicted_k_index: float,
) -> KMeshEntry:
    """Select the nearest indexed k-mesh entry for a model prediction."""
    target_index = max(1, math.ceil(predicted_k_index))
    max_index = entries[-1].k_index
    target_index = min(target_index, max_index)

    return entries[target_index - 1]


def ml_kmesh_advisor(spec: ModelSpec) -> KMeshAdvisor:
    """Return a Kmesh-stage backend that uses an ML model when no hint is set."""

    def advisor(structure, hints, kpoint_advice):
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)
        return advise_kpoints(structure, spec)

    return advisor


def advise_kpoints(
    structure: Structure,
    spec: ModelSpec,
) -> KPointSelection:
    """Select a k-point grid from an ML-predicted k-index."""
    features = extract_cslr_features(structure)
    model = load_model(spec)
    predicted_k_index = predict(model, features)

    candidate_distances = generate_candidate_k_distances(structure)
    entries = build_kmesh_entries(structure, candidate_distances)
    selected_entry = _select_kmesh_entry(entries, predicted_k_index)

    return KPointSelection(
        mesh_type="monkhorst-pack",
        grid=selected_entry.mesh,
        shift=(0, 0, 0),
        provenance=Provenance(
            source="model",
            reason="Select nearest k-mesh entry from predicted k-index.",
            data_source=spec.name,
        ),
    )
