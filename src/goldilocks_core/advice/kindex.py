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
from goldilocks_core.kmesh.math import (
    build_kmesh_entries,
    generate_candidate_k_distances,
)
from goldilocks_core.ml.kindex import predict_kindex


def _select_kmesh_entry(
    entries: list[KMeshEntry],
    predicted_k_index: float,
) -> KMeshEntry:
    target_index = max(0, math.ceil(predicted_k_index))
    max_index = entries[-1].k_index
    target_index = min(target_index, max_index)

    return entries[target_index]


def ml_kmesh_advisor(spec: ModelSpec) -> KMeshAdvisor:
    def advisor(structure: Structure) -> KPointSelection:
        return advise_kpoints(structure, spec)

    return advisor


def advise_kpoints(
    structure: Structure,
    spec: ModelSpec,
) -> KPointSelection:
    predicted_k_index = predict_kindex(structure, spec)

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
