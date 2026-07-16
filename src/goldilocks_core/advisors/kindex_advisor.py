"""K-point recommendation utilities."""

from __future__ import annotations

import math
from threading import Lock

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    KMeshAdvisor,
    KMeshEntry,
    KPointAdvice,
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


class MlKmeshAdvisor:
    """Lazy reusable k-index model backend and runtime lifecycle resource."""

    def __init__(self, spec: ModelSpec) -> None:
        """Configure one model without loading it."""
        self._spec = spec
        self._lock = Lock()
        self._model: object | None = None
        self._load_error: Exception | None = None
        self._closed = False

    def __call__(
        self,
        structure: Structure,
        hints: CalculationHints,
        kpoint_advice: KPointAdvice,
    ) -> KPointSelection:
        """Resolve a hint or select a grid using the lazily loaded model."""
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)
        return _advise_kpoints(structure, self._load(), self._spec)

    def reset(self) -> None:
        """Discard a loaded model or cached load failure for lazy retry."""
        with self._lock:
            if self._closed:
                raise RuntimeError("ML k-mesh advisor is closed.")
            self._model = None
            self._load_error = None

    def close(self) -> None:
        """Release the model reference permanently."""
        with self._lock:
            if self._closed:
                return
            self._model = None
            self._load_error = None
            self._closed = True

    def _load(self) -> object:
        """Load once or re-raise the cached load failure."""
        with self._lock:
            if self._closed:
                raise RuntimeError("ML k-mesh advisor is closed.")
            if self._load_error is not None:
                raise self._load_error
            if self._model is None:
                try:
                    self._model = load_model(self._spec)
                except Exception as error:
                    self._load_error = error
                    raise
            return self._model


def ml_kmesh_advisor(spec: ModelSpec) -> KMeshAdvisor:
    """Return a lifecycle-managed ML Kmesh backend for one model specification."""
    return MlKmeshAdvisor(spec)


def advise_kpoints(
    structure: Structure,
    spec: ModelSpec,
) -> KPointSelection:
    """Select a k-point grid from an ML-predicted k-index."""
    return _advise_kpoints(structure, load_model(spec), spec)


def _advise_kpoints(
    structure: Structure,
    model: object,
    spec: ModelSpec,
) -> KPointSelection:
    """Select a k-point grid from one loaded model and extracted features."""
    features = extract_cslr_features(structure)
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
