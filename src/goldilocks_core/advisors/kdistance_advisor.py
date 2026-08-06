"""Quantile Random Forest k-distance advisor."""

from __future__ import annotations

import os
from functools import cache

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    KMeshAdvisor,
    KPointAdvice,
    KPointSelection,
    PathLike,
    Provenance,
)
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.kmesh.math import k_distance_to_mesh
from goldilocks_core.ml.model_registry import QrfKpointsConfig, load_default_qrf_config
from goldilocks_core.ml.qrf import predict_kdistance


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


def qrf_kdistance_advisor(
    config: QrfKpointsConfig,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return a lazy QRF k-point advisor."""

    def advisor(
        structure: Structure,
        hints: CalculationHints,
        kpoint_advice: KPointAdvice,
    ) -> KPointSelection:
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)

        prediction = predict_kdistance(
            structure,
            config,
            metallicity_checkpoint=metallicity_checkpoint,
            metallicity_atom_init=metallicity_atom_init,
        )
        return kdistance_to_selection(
            structure,
            prediction.median,
            prediction.lower,
            prediction.upper,
            data_source=prediction.data_source,
            confidence=prediction.confidence,
        )

    return advisor


def default_kmesh_advisor(
    *,
    registry_path: PathLike | None = None,
    config: QrfKpointsConfig | None = None,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
) -> KMeshAdvisor:
    """Return the configured default QRF k-point advisor."""
    checkpoint = metallicity_checkpoint or os.environ.get(
        "GOLDILOCKS_METALLICITY_CHECKPOINT"
    )
    atom_init = metallicity_atom_init or os.environ.get(
        "GOLDILOCKS_METALLICITY_ATOM_INIT"
    )

    @cache
    def configured_advisor() -> KMeshAdvisor:
        active_config = config or load_default_qrf_config(registry_path)
        return qrf_kdistance_advisor(active_config, checkpoint, atom_init)

    def advisor(
        structure: Structure,
        hints: CalculationHints,
        kpoint_advice: KPointAdvice,
    ) -> KPointSelection:
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)
        return configured_advisor()(structure, hints, kpoint_advice)

    return advisor
