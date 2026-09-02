from __future__ import annotations

from threading import Lock

from pymatgen.core import Structure

from goldilocks_core.assets.store import AssetStore
from goldilocks_core.kmesh.math import k_distance_to_mesh
from goldilocks_core.ml.model_registry import QrfKpointsConfig, load_default_qrf_config
from goldilocks_core.ml.qrf.inference import (
    QrfResources,
    load_qrf_resources,
    predict_kdistance_with_resources,
)
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict, PathLike


def kdistance_to_selection(
    structure: Structure,
    median: float,
    lower: float,
    upper: float,
    *,
    data_source: str,
    confidence: float,
    mesh_type: str = "monkhorst-pack",
) -> JsonDict:
    return {
        "grid": list(k_distance_to_mesh(structure, median)),
        "shift": [0, 0, 0],
        "mesh_type": mesh_type,
        "provenance": Provenance(
            source="model",
            reason=(
                f"ML-predicted k-point distance {median:.4f} Å⁻¹ "
                f"(interval {lower:.4f}-{upper:.4f} Å⁻¹)."
            ),
            data_source=data_source,
            confidence=confidence,
        ),
    }


class QrfBackend:
    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        config: QrfKpointsConfig | None = None,
        metallicity_checkpoint: str | None = None,
        metallicity_atom_init: str | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self._registry_path = registry_path
        self._config = config
        self._metallicity_checkpoint = metallicity_checkpoint
        self._metallicity_atom_init = metallicity_atom_init
        self._asset_store = asset_store
        self._resources: QrfResources | None = None
        self._closed = False
        self._load_lock = Lock()

    def __call__(self, structure: Structure) -> JsonDict:
        if self._closed:
            raise RuntimeError("QrfBackend is closed.")
        resources = self._resources
        if resources is None:
            with self._load_lock:
                resources = self._resources
                if resources is None:
                    resources = self._load_resources()
                    self._resources = resources
        prediction = predict_kdistance_with_resources(
            structure, self._config, resources
        )
        return kdistance_to_selection(
            structure,
            prediction.median,
            prediction.lower,
            prediction.upper,
            data_source=prediction.data_source,
            confidence=prediction.confidence,
        )

    def reset(self) -> None:
        with self._load_lock:
            self._resources = None

    def close(self) -> None:
        with self._load_lock:
            self._resources = None
            self._closed = True

    def _load_resources(self) -> QrfResources:
        if self._config is None:
            self._config = load_default_qrf_config(self._registry_path)
        return load_qrf_resources(
            self._config,
            metallicity_checkpoint=self._metallicity_checkpoint,
            metallicity_atom_init=self._metallicity_atom_init,
            asset_store=self._asset_store,
        )
