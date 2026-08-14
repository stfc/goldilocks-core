"""Pure Select-stage pseudopotential choices."""

from __future__ import annotations

from collections.abc import Sequence

from pymatgen.core import Structure

from goldilocks_core.contracts import (
    Provenance,
    PseudoMetadata,
    PseudopotentialRequirements,
    PseudopotentialSelection,
    SelectionRecord,
)


def select_pseudopotentials(
    structure: Structure,
    requirements: PseudopotentialRequirements,
    metadata: Sequence[PseudoMetadata],
) -> SelectionRecord:
    """Select one concrete pseudopotential per element from available metadata."""
    available = tuple(metadata)
    selections = tuple(
        _select_for_element(element.symbol, requirements, available)
        for element in sorted(
            structure.composition.elements, key=lambda item: item.symbol
        )
    )
    warnings = tuple(
        warning for selection in selections for warning in selection.warnings
    )
    return SelectionRecord(pseudopotentials=selections, warnings=warnings)


def _select_for_element(
    element: str,
    requirements: PseudopotentialRequirements,
    metadata: tuple[PseudoMetadata, ...],
) -> PseudopotentialSelection:
    """Select the deterministic highest-ranked candidate for one element."""
    candidates = [
        item
        for item in metadata
        if item.element == element
        and item.functional == requirements.functional
        and (
            requirements.pseudo_type is None
            or item.pseudo_type == requirements.pseudo_type
        )
        and item.relativistic == requirements.relativistic
    ]
    exact_accuracy = [
        item for item in candidates if item.accuracy == requirements.accuracy
    ]
    candidates = exact_accuracy or [
        item for item in candidates if item.accuracy is None
    ]

    if not candidates:
        warning = _missing_pseudo_warning(element, requirements, metadata)
        return PseudopotentialSelection(
            element=element,
            filename=None,
            filepath=None,
            functional=None,
            ecutwfc_ry=None,
            ecutrho_ry=None,
            provenance=Provenance(
                source="fallback",
                reason="No pseudopotential satisfies the scientific requirements.",
                warnings=(warning,),
            ),
            warnings=(warning,),
        )

    selected = min(candidates, key=_candidate_rank)
    ecutwfc = selected.cutoffs.ecutwfc_ry if selected.cutoffs else None
    ecutrho = selected.cutoffs.ecutrho_ry if selected.cutoffs else None
    warnings = _selection_warnings(element, selected, requirements)
    data_source = selected.table_id or selected.provider or selected.source_identifier
    return PseudopotentialSelection(
        element=element,
        filename=selected.filename,
        filepath=selected.filepath,
        functional=selected.functional,
        ecutwfc_ry=ecutwfc,
        ecutrho_ry=ecutrho,
        provenance=Provenance(
            source="lookup",
            reason=(
                "Select the deterministic highest-ranked pseudopotential "
                "satisfying the scientific requirements."
            ),
            data_source=data_source,
            warnings=warnings,
        ),
        warnings=warnings,
    )


def _candidate_rank(metadata: PseudoMetadata) -> tuple[int, str, str, str]:
    """Rank complete metadata first, then provenance-only deterministic fields."""
    complete_cutoffs = (
        metadata.cutoffs is not None
        and metadata.cutoffs.ecutwfc_ry is not None
        and metadata.cutoffs.ecutrho_ry is not None
    )
    return (
        0 if complete_cutoffs else 1,
        metadata.provider or "",
        metadata.source_identifier or "",
        metadata.filename,
    )


def _selection_warnings(
    element: str,
    selected: PseudoMetadata,
    requirements: PseudopotentialRequirements,
) -> tuple[str, ...]:
    """Return actionable warnings for accepted incomplete metadata."""
    warnings = list(selected.warnings)
    if selected.accuracy is None:
        warnings.append(
            f"Selected custom pseudopotential for {element} has no registered "
            f"accuracy tier; requested {requirements.accuracy}."
        )
    if selected.frozen_4f_core:
        warnings.append(
            f"Selected 3+ lanthanide pseudopotential for {element} freezes 4f "
            "electrons in the core and assumes a trivalent ion; verify this is "
            "appropriate, especially for Ce, Eu, or Yb."
        )

    missing = []
    if selected.cutoffs is None or selected.cutoffs.ecutwfc_ry is None:
        missing.append("ecutwfc_ry")
    if selected.cutoffs is None or selected.cutoffs.ecutrho_ry is None:
        missing.append("ecutrho_ry")
    if missing:
        warnings.append(
            f"Selected pseudopotential for {element} is missing cutoff metadata "
            f"for {', '.join(missing)}; provide finite positive values before "
            "generation."
        )
    return tuple(warnings)


def _missing_pseudo_warning(
    element: str,
    requirements: PseudopotentialRequirements,
    metadata: tuple[PseudoMetadata, ...],
) -> str:
    """Explain the first unsatisfied scientific requirement."""
    candidates = [item for item in metadata if item.element == element]
    if not candidates:
        return f"No available pseudopotential contains element {element}."

    functional = [
        item for item in candidates if item.functional == requirements.functional
    ]
    if not functional:
        available = ", ".join(
            sorted({item.functional or "unknown" for item in candidates})
        )
        return (
            f"Available pseudopotentials for {element} do not match functional "
            f"{requirements.functional}; available: {available}."
        )

    relativistic = [
        item for item in functional if item.relativistic == requirements.relativistic
    ]
    if not relativistic:
        return (
            f"No available {requirements.relativistic} "
            f"{requirements.functional} pseudopotential covers {element}."
        )

    typed = [
        item
        for item in relativistic
        if requirements.pseudo_type is None
        or item.pseudo_type == requirements.pseudo_type
    ]
    if not typed:
        return (
            f"No available pseudopotential for {element} matches type "
            f"{requirements.pseudo_type or 'any'}."
        )

    return (
        f"No available pseudopotential for {element} matches registered "
        f"accuracy {requirements.accuracy}; custom metadata with unknown accuracy "
        "is also absent."
    )
