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
    k_index_base: int = 1,
) -> KMeshEntry:
    # A model numbers its rungs from its own base; this ladder numbers them
    # from 1. Shifting here is what lets a record published against either
    # convention name the same mesh.
    on_ladder = predicted_k_index + (1 - k_index_base)
    target_index = max(1, math.ceil(on_ladder))
    max_k_index = entries[-1].k_index
    target_index = min(target_index, max_k_index)

    # k_index is 1-based; the list is not.
    return entries[target_index - 1]


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
    selected_entry = _select_kmesh_entry(entries, predicted_k_index, spec.k_index_base)

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
