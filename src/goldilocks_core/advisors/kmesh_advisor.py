"""K-point recommendation utilities."""

from __future__ import annotations

import math

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    AccuracyLevel,
    KMeshEntry,
    KPointsAdvice,
    ModelSpec,
)
from goldilocks_core.kmesh import (
    build_kmesh_entries,
    generate_candidate_k_distances,
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


def advise_kpoints(
    structure: Structure,
    spec: ModelSpec,
    accuracy_level: AccuracyLevel = "standard",
) -> KPointsAdvice:
    """Advise k-point settings for a structure."""
    features = extract_cslr_features(structure)
    model = load_model(spec)
    predicted_k_index = predict(model, features)

    candidate_distances = generate_candidate_k_distances(structure)
    entries = build_kmesh_entries(structure, candidate_distances)
    selected_entry = _select_kmesh_entry(entries, predicted_k_index)

    return KPointsAdvice(
        code="quantum_espresso",
        task="scf_single_point",
        mesh_type="monkhorst-pack",
        grid=selected_entry.mesh,
        shift=(0, 0, 0),
        accuracy_level=accuracy_level,
        advisor_kind="ml",
        advisor_name=spec.name,
    )
