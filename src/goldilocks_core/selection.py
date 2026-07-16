"""Select-stage concrete choices for the Core pipeline."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    KPointSelection,
    ParameterAdvice,
    Provenance,
    PseudopotentialSelection,
    SelectionRecord,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_selector import select_pseudos

_CUTOFF_FIELDS = ("ecutwfc_ry", "ecutrho_ry")


@dataclass(frozen=True, slots=True)
class _CutoffAssessment:
    """A validated cutoff value and its metadata trust status."""

    value: float | None
    status: str
    raw_value: Any = None


def select_parameters(
    structure: Structure,
    advice: ParameterAdvice,
    k_points: KPointSelection,
    metadata_list: Sequence[PseudoMetadata] | None = None,
) -> SelectionRecord:
    """Resolve advice into concrete pseudopotential selections.

    Args:
        structure: Structure whose elements require pseudopotentials.
        advice: Parameter advice produced by the Advise stage.
        k_points: Concrete k-point selection produced by the Kmesh stage.
        metadata_list: Available pseudopotential metadata. Missing or empty
            metadata is allowed and produces fallback selections with warnings.

    Returns:
        A ``SelectionRecord`` containing the supplied k-point selection,
        one pseudopotential selection per element, and selection warnings.
    """
    pseudo_selections = _select_pseudopotentials(
        structure,
        advice,
        list(metadata_list or ()),
    )
    warnings = tuple(
        warning for selection in pseudo_selections for warning in selection.warnings
    )

    return SelectionRecord(
        k_points=k_points,
        pseudopotentials=pseudo_selections,
        warnings=warnings,
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
    cutoff_assessments = {
        field: _assess_cutoff(selected, field) for field in _CUTOFF_FIELDS
    }
    warnings = _selection_warnings(
        element=element,
        selected=selected,
        pseudo_mode=pseudo_advice.pseudo_mode,
        cutoff_assessments=cutoff_assessments,
    )

    return PseudopotentialSelection(
        element=element,
        filename=selected.filename,
        filepath=selected.filepath,
        ecutwfc_ry=cutoff_assessments["ecutwfc_ry"].value,
        ecutrho_ry=cutoff_assessments["ecutrho_ry"].value,
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
    """Return whether metadata contains two finite, strictly positive cutoffs."""
    return all(
        _assess_cutoff(metadata, field).status == "valid" for field in _CUTOFF_FIELDS
    )


def _assess_cutoff(metadata: PseudoMetadata, field: str) -> _CutoffAssessment:
    """Validate one untrusted metadata cutoff without constructing a record."""
    cutoffs = metadata.sssp_recommended_cutoff
    if cutoffs is None:
        return _CutoffAssessment(value=None, status="missing")
    if not isinstance(cutoffs, Mapping):
        return _CutoffAssessment(value=None, status="invalid", raw_value=cutoffs)
    if field not in cutoffs or cutoffs[field] is None:
        return _CutoffAssessment(value=None, status="missing")

    raw_value = cutoffs[field]
    if isinstance(raw_value, (bool, np.bool_)):
        return _CutoffAssessment(
            value=None,
            status="invalid",
            raw_value=raw_value,
        )

    try:
        value = float(raw_value)
    except (OverflowError, TypeError, ValueError):
        return _CutoffAssessment(
            value=None,
            status="invalid",
            raw_value=raw_value,
        )

    if not math.isfinite(value) or value <= 0:
        return _CutoffAssessment(
            value=None,
            status="invalid",
            raw_value=raw_value,
        )

    return _CutoffAssessment(value=value, status="valid", raw_value=raw_value)


def _selection_warnings(
    *,
    element: str,
    selected: PseudoMetadata,
    pseudo_mode: str,
    cutoff_assessments: dict[str, _CutoffAssessment],
) -> tuple[str, ...]:
    """Return actionable warnings about the selected pseudo metadata."""
    warnings: list[str] = []

    if not _metadata_matches_mode(selected, pseudo_mode):
        warnings.append(
            f"Selected pseudopotential for {element} does not explicitly match "
            f"pseudo mode '{pseudo_mode}'."
        )

    missing = [
        field
        for field, assessment in cutoff_assessments.items()
        if assessment.status == "missing"
    ]
    if missing:
        warnings.append(
            f"Selected pseudopotential for {element} is missing cutoff metadata "
            f"for {', '.join(missing)}; provide finite positive values before "
            "generation."
        )

    invalid = [
        f"{field}={assessment.raw_value!r}"
        for field, assessment in cutoff_assessments.items()
        if assessment.status == "invalid"
    ]
    if invalid:
        warnings.append(
            f"Selected pseudopotential for {element} has invalid cutoff metadata "
            f"({', '.join(invalid)}); replace it with finite positive values before "
            "generation."
        )

    return tuple(warnings)
