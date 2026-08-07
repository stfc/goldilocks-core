"""Kmesh stage backend: resolve k-point advice and hints into a selection."""

from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    KPointAdvice,
    KPointSelection,
    Provenance,
)
from goldilocks_core.kmesh.math import k_distance_to_mesh


def resolve_kpoints_from_advice(
    structure: Structure,
    hints: CalculationHints,
    advice: KPointAdvice,
) -> KPointSelection:
    """Resolve k-point advice and hints into a concrete unshifted mesh."""
    if hints.k_grid is not None:
        return KPointSelection(
            grid=hints.k_grid,
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
                warnings=advice.provenance.warnings,
            ),
        )

    if hints.k_spacing is not None:
        return KPointSelection(
            grid=k_distance_to_mesh(structure, hints.k_spacing),
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
                data_source="pymatgen solid-state reciprocal lattice",
                warnings=advice.provenance.warnings,
            ),
        )

    if advice.explicit_grid is not None:
        return KPointSelection(
            grid=advice.explicit_grid,
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source=advice.provenance.source,
                reason="Use the explicit grid from k-point advice.",
                data_source=advice.provenance.data_source,
                confidence=advice.provenance.confidence,
                warnings=advice.provenance.warnings,
            ),
        )

    # With KPointAdvice's exactly-one invariant, reaching here means spacing is set.
    return KPointSelection(
        grid=k_distance_to_mesh(structure, advice.spacing),
        shift=(0, 0, 0),
        mesh_type=advice.mesh_type,
        provenance=Provenance(
            source=advice.provenance.source,
            reason="Convert advised VASP-style k-point spacing into a mesh.",
            data_source="pymatgen solid-state reciprocal lattice",
            warnings=advice.provenance.warnings,
        ),
    )
