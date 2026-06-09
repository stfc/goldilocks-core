"""Select-stage concrete choices for the Core pipeline."""

from __future__ import annotations

from typing import Any

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    KPointAdvice,
    KPointSelection,
    ParameterAdvice,
    Provenance,
    PseudopotentialSelection,
    SelectionRecord,
)
from goldilocks_core.kmesh import k_distance_to_mesh
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_selector import select_pseudos


def select_parameters(
    structure: Structure,
    advice: ParameterAdvice,
    metadata_list: list[PseudoMetadata] | None = None,
) -> SelectionRecord:
    """Resolve advice into concrete k-point and pseudopotential selections."""
    pseudo_selections = _select_pseudopotentials(
        structure,
        advice,
        metadata_list or [],
    )
    warnings = tuple(
        warning for selection in pseudo_selections for warning in selection.warnings
    )

    return SelectionRecord(
        k_points=_select_k_points(structure, advice.k_points),
        pseudopotentials=pseudo_selections,
        warnings=warnings,
    )


def _select_k_points(
    structure: Structure,
    advice: KPointAdvice,
) -> KPointSelection:
    """Resolve k-point advice into a concrete unshifted mesh."""
    if advice.explicit_grid is not None:
        return KPointSelection(
            grid=advice.explicit_grid,
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(
                source="user_hint",
                reason="Use the explicit grid from k-point advice.",
            ),
        )

    if advice.spacing is None:
        raise ValueError("k-point advice must contain spacing or an explicit grid")

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


def _select_pseudopotentials(
    structure: Structure,
    advice: ParameterAdvice,
    metadata_list: list[PseudoMetadata],
) -> tuple[PseudopotentialSelection, ...]:
    """Select one pseudopotential per element where metadata is available."""
    elements = tuple(
        sorted(element.symbol for element in structure.composition.elements)
    )

    return tuple(
        _select_pseudopotential_for_element(element, advice, metadata_list)
        for element in elements
    )


def _select_pseudopotential_for_element(
    element: str,
    advice: ParameterAdvice,
    metadata_list: list[PseudoMetadata],
) -> PseudopotentialSelection:
    """Select the first deterministic matching pseudopotential for an element."""
    pseudo_advice = advice.pseudopotentials
    candidates = select_pseudos(
        metadata_list,
        element=element,
        functional=pseudo_advice.functional,
        pseudo_type=pseudo_advice.pseudo_type,
        relativistic=pseudo_advice.relativistic_mode,
    )
    candidates = sorted(
        candidates,
        key=lambda metadata: _rank_pseudo_candidate(
            metadata,
            pseudo_advice.pseudo_mode,
        ),
    )

    if not candidates:
        warning = (
            "No pseudopotential metadata matched "
            f"{element} / {pseudo_advice.functional} / "
            f"{pseudo_advice.relativistic_mode}."
        )
        return PseudopotentialSelection(
            element=element,
            filename=None,
            filepath=None,
            ecutwfc_ry=None,
            ecutrho_ry=None,
            provenance=Provenance(
                source="fallback",
                reason="No matching pseudopotential was available.",
                warnings=(warning,),
            ),
            warnings=(warning,),
        )

    selected = candidates[0]
    cutoffs = selected.sssp_recommended_cutoff or {}
    ecutwfc = _to_float(cutoffs.get("ecutwfc_ry"))
    ecutrho = _to_float(cutoffs.get("ecutrho_ry"))
    warnings = _selection_warnings(
        element=element,
        selected=selected,
        pseudo_mode=pseudo_advice.pseudo_mode,
        ecutwfc=ecutwfc,
        ecutrho=ecutrho,
    )

    return PseudopotentialSelection(
        element=element,
        filename=selected.filename,
        filepath=selected.filepath,
        ecutwfc_ry=ecutwfc,
        ecutrho_ry=ecutrho,
        provenance=Provenance(
            source="lookup",
            reason="Select the highest-ranked deterministic pseudo matching advice.",
            data_source=selected.library or selected.source_set,
            warnings=warnings,
        ),
        warnings=warnings,
    )


def _rank_pseudo_candidate(
    metadata: PseudoMetadata,
    pseudo_mode: str,
) -> tuple[int, int, int, str, str]:
    """Return an explicit deterministic ranking key for pseudo candidates."""
    mode_rank = 0 if _metadata_matches_mode(metadata, pseudo_mode) else 1
    cutoff_rank = 0 if _has_complete_cutoffs(metadata) else 1
    sssp_rank = 0 if metadata.is_sssp else 1
    source = metadata.source_set or metadata.library or ""
    return (mode_rank, cutoff_rank, sssp_rank, source, metadata.filename)


def _metadata_matches_mode(metadata: PseudoMetadata, pseudo_mode: str) -> bool:
    """Return whether metadata appears to match an efficiency/precision mode."""
    mode = pseudo_mode.lower()
    searchable = " ".join(
        value.lower()
        for value in (
            metadata.library,
            metadata.source_set,
            metadata.source_pseudopotential,
            metadata.filename,
        )
        if value
    )
    if mode in searchable:
        return True

    if "efficiency" in searchable or "precision" in searchable:
        return False

    return metadata.is_sssp or (metadata.library or "").lower() == "sssp"


def _has_complete_cutoffs(metadata: PseudoMetadata) -> bool:
    """Return whether metadata contains both required QE cutoff values."""
    cutoffs = metadata.sssp_recommended_cutoff or {}
    return (
        _to_float(cutoffs.get("ecutwfc_ry")) is not None
        and _to_float(cutoffs.get("ecutrho_ry")) is not None
    )


def _selection_warnings(
    *,
    element: str,
    selected: PseudoMetadata,
    pseudo_mode: str,
    ecutwfc: float | None,
    ecutrho: float | None,
) -> tuple[str, ...]:
    """Return structured warnings about the selected pseudo metadata."""
    warnings: list[str] = []

    if not _metadata_matches_mode(selected, pseudo_mode):
        warnings.append(
            f"Selected pseudopotential for {element} does not explicitly match "
            f"pseudo mode '{pseudo_mode}'."
        )

    if ecutwfc is None or ecutrho is None:
        warnings.append(
            f"Selected pseudopotential for {element} lacks complete cutoff metadata."
        )

    return tuple(warnings)


def _to_float(value: Any) -> float | None:
    """Convert cutoff metadata values to floats when possible."""
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None
