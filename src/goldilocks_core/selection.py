from __future__ import annotations

from collections.abc import Sequence

from pymatgen.core import Structure

from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.serialization import to_jsonable
from goldilocks_core.types import JsonDict


class SelectionRecord:
    """Marker for the selection record; the value is a dict.

    Keys: ``pseudopotentials`` (a list of per-element selection documents
    carrying element, filename, filepath, functional, relativistic,
    ecutwfc_ry, ecutrho_ry, provenance, warnings) and ``warnings``.
    """


def selection_portable(selection: JsonDict) -> JsonDict:
    """Portable projection of a selection document: converts every value to
    JSON-able form and drops each pseudopotential's host filepath."""
    pseudopotentials = [
        to_jsonable({key: value for key, value in item.items() if key != "filepath"})
        for item in selection["pseudopotentials"]
    ]
    return {
        "pseudopotentials": pseudopotentials,
        "warnings": list(selection["warnings"]),
    }


LANTHANIDES = frozenset(
    [
        "La",
        "Ce",
        "Pr",
        "Nd",
        "Pm",
        "Sm",
        "Eu",
        "Gd",
        "Tb",
        "Dy",
        "Ho",
        "Er",
        "Tm",
        "Yb",
        "Lu",
    ]
)
ACTINIDES = frozenset(
    [
        "Ac",
        "Th",
        "Pa",
        "U",
        "Np",
        "Pu",
        "Am",
        "Cm",
        "Bk",
        "Cf",
        "Es",
        "Fm",
        "Md",
        "No",
        "Lr",
    ]
)

_LANTHANIDE_ACTINIDE_REASON = (
    "is a lanthanide/actinide: only SSSP pseudopotentials are used for these "
    "elements, because PseudoDojo's lanthanide table freezes 4f electrons in "
    "the core assuming a trivalent ion (wrong for Eu, Yb, and Ce) and no "
    "PseudoDojo table covers actinides at all. This also means no spin-orbit "
    "coupling for these elements: SSSP has no fully-relativistic table. "
    "Install SSSP with `goldilocks assets install sssp-pbesol-efficiency-sr` "
    "and select it with `--pseudo-table sssp-pbesol-efficiency-sr`. "
)


def select_pseudopotentials(
    structure: Structure,
    requirements: JsonDict,
    metadata: Sequence[PseudoMetadata],
) -> JsonDict:
    available = tuple(metadata)
    selections = [
        _select_for_element(element.symbol, requirements, available)
        for element in sorted(
            structure.composition.elements, key=lambda item: item.symbol
        )
    ]
    warnings = [
        warning for selection in selections for warning in selection["warnings"]
    ]
    return {"pseudopotentials": selections, "warnings": warnings}


def _select_for_element(
    element: str,
    requirements: JsonDict,
    metadata: tuple[PseudoMetadata, ...],
) -> JsonDict:
    candidates = [
        item
        for item in metadata
        if item.element == element
        and item.functional == requirements["functional"]
        and (
            requirements["pseudo_type"] is None
            or item.pseudo_type == requirements["pseudo_type"]
        )
        and _relativistic_compatible(item, requirements)
    ]
    if element in LANTHANIDES or element in ACTINIDES:
        candidates = [item for item in candidates if item.provider == "sssp"]
    exact_accuracy = [
        item for item in candidates if item.accuracy == requirements["accuracy"]
    ]
    candidates = exact_accuracy or [
        item for item in candidates if item.accuracy is None
    ]

    if not candidates:
        warning = _missing_pseudo_warning(element, requirements, metadata)
        return {
            "element": element,
            "filename": None,
            "filepath": None,
            "functional": None,
            "relativistic": None,
            "ecutwfc_ry": None,
            "ecutrho_ry": None,
            "provenance": Provenance(
                source="fallback",
                reason="No pseudopotential satisfies the scientific requirements.",
                warnings=(warning,),
            ),
            "warnings": [warning],
        }

    selected = min(candidates, key=_candidate_rank)
    ecutwfc = selected.cutoffs["ecutwfc_ry"] if selected.cutoffs else None
    ecutrho = selected.cutoffs["ecutrho_ry"] if selected.cutoffs else None
    warnings = _selection_warnings(element, selected, requirements)
    data_source = selected.table_id or selected.provider or selected.source_identifier
    return {
        "element": element,
        "filename": selected.filename,
        "filepath": selected.filepath,
        "functional": selected.functional,
        "relativistic": selected.relativistic,
        "ecutwfc_ry": ecutwfc,
        "ecutrho_ry": ecutrho,
        "provenance": Provenance(
            source="lookup",
            reason=(
                "Select the deterministic highest-ranked pseudopotential "
                "satisfying the scientific requirements."
            ),
            data_source=data_source,
            warnings=warnings,
        ),
        "warnings": list(warnings),
    }


def _relativistic_compatible(
    metadata: PseudoMetadata,
    requirements: JsonDict,
) -> bool:
    return metadata.relativistic == requirements["relativistic"] or (
        metadata.provider == "sssp"
        and metadata.relativistic == "non-relativistic"
        and requirements["relativistic"] == "scalar"
    )


def _candidate_rank(metadata: PseudoMetadata) -> tuple[int, int, str, str, str]:
    complete_cutoffs = (
        metadata.cutoffs is not None
        and metadata.cutoffs["ecutwfc_ry"] is not None
        and metadata.cutoffs["ecutrho_ry"] is not None
    )
    return (
        0 if complete_cutoffs else 1,
        0 if metadata.provider == "sssp" else 1,
        metadata.provider or "",
        metadata.source_identifier or "",
        metadata.filename,
    )


def _selection_warnings(
    element: str,
    selected: PseudoMetadata,
    requirements: JsonDict,
) -> tuple[str, ...]:
    warnings = list(selected.warnings)
    if selected.relativistic != requirements["relativistic"]:
        warnings.append(
            f"Selected SSSP pseudopotential for {element} declares "
            f"{selected.relativistic} treatment within a "
            f"{requirements['relativistic']} table; verify this compatibility."
        )
    if selected.accuracy is None:
        warnings.append(
            f"Selected custom pseudopotential for {element} has no registered "
            f"accuracy tier; requested {requirements['accuracy']}."
        )
    if selected.frozen_4f_core:
        warnings.append(
            f"Selected 3+ lanthanide pseudopotential for {element} freezes 4f "
            "electrons in the core and assumes a trivalent ion; verify this is "
            "appropriate, especially for Ce, Eu, or Yb."
        )

    missing = []
    if selected.cutoffs is None or selected.cutoffs["ecutwfc_ry"] is None:
        missing.append("ecutwfc_ry")
    if selected.cutoffs is None or selected.cutoffs["ecutrho_ry"] is None:
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
    requirements: JsonDict,
    metadata: tuple[PseudoMetadata, ...],
) -> str:
    message = _missing_pseudo_reason(element, requirements, metadata)
    if element in LANTHANIDES or element in ACTINIDES:
        return f"{element} {_LANTHANIDE_ACTINIDE_REASON}{message}"
    return message


def _missing_pseudo_reason(
    element: str,
    requirements: JsonDict,
    metadata: tuple[PseudoMetadata, ...],
) -> str:
    candidates = [item for item in metadata if item.element == element]
    if not candidates:
        return f"No available pseudopotential contains element {element}."

    functional = [
        item for item in candidates if item.functional == requirements["functional"]
    ]
    if not functional:
        available = ", ".join(
            sorted({item.functional or "unknown" for item in candidates})
        )
        return (
            f"Available pseudopotentials for {element} do not match functional "
            f"{requirements['functional']}; available: {available}."
        )

    relativistic = [
        item for item in functional if item.relativistic == requirements["relativistic"]
    ]
    if not relativistic:
        return (
            f"No available {requirements['relativistic']} "
            f"{requirements['functional']} pseudopotential covers {element}."
        )

    typed = [
        item
        for item in relativistic
        if requirements["pseudo_type"] is None
        or item.pseudo_type == requirements["pseudo_type"]
    ]
    if not typed:
        return (
            f"No available pseudopotential for {element} matches type "
            f"{requirements['pseudo_type'] or 'any'}."
        )

    return (
        f"No available pseudopotential for {element} matches registered "
        f"accuracy {requirements['accuracy']}; custom metadata with unknown accuracy "
        "is also absent."
    )
