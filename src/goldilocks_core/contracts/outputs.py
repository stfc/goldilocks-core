"""Record types available to Core queries, keyed by stable transport ids."""

from __future__ import annotations

from goldilocks_core.contracts.advice import ParameterAdvice
from goldilocks_core.contracts.analysis import StructureAnalysisRecord
from goldilocks_core.contracts.kpoints import KPointSelection
from goldilocks_core.contracts.registry import record_type_id
from goldilocks_core.contracts.result import GeneratedFiles
from goldilocks_core.contracts.selection import SelectionRecord

OUTPUT_RECORD_TYPES: tuple[type, ...] = (
    StructureAnalysisRecord,
    ParameterAdvice,
    KPointSelection,
    SelectionRecord,
    GeneratedFiles,
)
"""Record types callers may request from the SCF task graph."""

OUTPUT_TYPES_BY_ID: dict[str, type] = {
    record_type_id(record_type): record_type for record_type in OUTPUT_RECORD_TYPES
}
"""Query record types keyed by their stable transport identifiers."""


def resolve_output_types(ids: list[str] | tuple[str, ...]) -> tuple[type, ...]:
    """Resolve stable transport record ids to Core query output types."""
    if not ids or any(
        not isinstance(record_id, str) or not record_id.strip() for record_id in ids
    ):
        raise ValueError("outputs must contain at least one record type id")

    normalized = [record_id.strip() for record_id in ids]
    unknown = [
        record_id for record_id in normalized if record_id not in OUTPUT_TYPES_BY_ID
    ]
    if unknown:
        available = ", ".join(OUTPUT_TYPES_BY_ID)
        invalid = ", ".join(unknown)
        raise ValueError(
            f"Unknown output record type id(s): {invalid}. Available: {available}"
        )
    return tuple(OUTPUT_TYPES_BY_ID[record_id] for record_id in normalized)
