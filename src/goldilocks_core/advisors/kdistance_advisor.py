"""Quantile Random Forest k-distance advisor."""

from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import (
    KPointSelection,
    PathLike,
    Provenance,
)
from goldilocks_core.kmesh.math import k_distance_to_mesh
from goldilocks_core.ml.model_registry import QrfKpointsConfig, load_default_qrf_config
from goldilocks_core.ml.qrf import predict_kdistance_with_resources
from goldilocks_core.ml.qrf.inference import QrfResources, load_qrf_resources


def kdistance_to_selection(
    structure: Structure,
    median: float,
    lower: float,
    upper: float,
    *,
    data_source: str,
    confidence: float,
    mesh_type: str = "monkhorst-pack",
) -> KPointSelection:
    """Build a concrete k-point selection from a predicted interval."""
    return KPointSelection(
        grid=k_distance_to_mesh(structure, median),
        shift=(0, 0, 0),
        mesh_type=mesh_type,
        provenance=Provenance(
            source="model",
            reason=(
                f"ML-predicted k-point distance {median:.4f} Å⁻¹ "
                f"(interval {lower:.4f}-{upper:.4f} Å⁻¹)."
            ),
            data_source=data_source,
            confidence=confidence,
        ),
    )


class QrfKDistanceBackend:
    """Stateful QRF k-distance advisor owning its loaded model resources.

    Lazily loads the QRF model + metallicity model on first use; ``reset``
    discards them so the next call reloads; ``close`` releases them.
    A fresh instance has no loaded state. Captured config paths are
    retained across ``reset``.
    """

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

    def __call__(self, structure: Structure) -> KPointSelection:
        """Predict a k-point selection for ``structure`` using the QRF model."""
        if self._closed:
            raise RuntimeError("QrfKDistanceBackend is closed.")
        if self._resources is None:
            self._resources = self._load_resources()
        prediction = predict_kdistance_with_resources(
            structure, self._config, self._resources
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
        """Discard loaded model resources; the next call reloads."""
        self._resources = None

    def close(self) -> None:
        """Release loaded model resources; the backend is unusable after this."""
        self._resources = None
        self._closed = True

    def _load_resources(self) -> QrfResources:
        """Load the config (if deferred) and the model resources."""
        if self._config is None:
            self._config = load_default_qrf_config(self._registry_path)
        return load_qrf_resources(
            self._config,
            metallicity_checkpoint=self._metallicity_checkpoint,
            metallicity_atom_init=self._metallicity_atom_init,
            asset_store=self._asset_store,
        )
