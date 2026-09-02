from __future__ import annotations

import math

from pymatgen.core import Structure

from goldilocks_core.kmesh.math import (
    build_kmesh_entries,
    generate_candidate_k_distances,
)
from goldilocks_core.kmesh.resolve import KMeshAdvisor
from goldilocks_core.ml.kindex.inference import predict_kindex
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict, KPointGrid


def _select_kmesh_entry(
    entries: list[tuple[int, KPointGrid]],
    predicted_k_index: float,
) -> tuple[int, KPointGrid]:
    target_index = max(1, math.ceil(predicted_k_index))
    max_index = entries[-1][0]
    target_index = min(target_index, max_index)

    return entries[target_index - 1]


def ml_kmesh_advisor(spec: ModelSpec) -> KMeshAdvisor:
    def advisor(structure: Structure) -> JsonDict:
        return advise_kpoints(structure, spec)

    return advisor


def advise_kpoints(
    structure: Structure,
    spec: ModelSpec,
) -> JsonDict:
    predicted_k_index = predict_kindex(structure, spec)

    candidate_distances = generate_candidate_k_distances(structure)
    entries = build_kmesh_entries(structure, candidate_distances)
    selected_entry = _select_kmesh_entry(entries, predicted_k_index)

    return {
        "mesh_type": "monkhorst-pack",
        "grid": list(selected_entry[1]),
        "shift": [0, 0, 0],
        "provenance": Provenance(
            source="model",
            reason="Select nearest k-mesh entry from predicted k-index.",
            data_source=spec.name,
        ),
    }
