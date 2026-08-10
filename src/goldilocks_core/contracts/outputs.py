"""Record types available to Core queries."""

from __future__ import annotations

from goldilocks_core.contracts.records import (
    GeneratedFiles,
    KPointSelection,
    ParameterAdvice,
    SelectionRecord,
    StructureAnalysisRecord,
)

OUTPUT_RECORD_TYPES: tuple[type, ...] = (
    StructureAnalysisRecord,
    ParameterAdvice,
    KPointSelection,
    SelectionRecord,
    GeneratedFiles,
)
"""Record types callers may request from the SCF task graph."""

OUTPUT_TYPES_BY_NAME = {
    output_type.__name__: output_type for output_type in OUTPUT_RECORD_TYPES
}
"""Query record types keyed by their public contract names."""


def resolve_output_types(names: list[str] | tuple[str, ...]) -> tuple[type, ...]:
    """Resolve public record names to Core query output types."""
    if not names or any(
        not isinstance(name, str) or not name.strip() for name in names
    ):
        raise ValueError("outputs must contain at least one record type name")

    normalized = [name.strip() for name in names]
    unknown = [name for name in normalized if name not in OUTPUT_TYPES_BY_NAME]
    if unknown:
        available = ", ".join(OUTPUT_TYPES_BY_NAME)
        invalid = ", ".join(unknown)
        raise ValueError(
            f"Unknown output record type(s): {invalid}. Available: {available}"
        )
    return tuple(OUTPUT_TYPES_BY_NAME[name] for name in normalized)
