from __future__ import annotations

from goldilocks_core.contracts.advice import ParameterAdvice
from goldilocks_core.contracts.analysis import StructureAnalysisRecord
from goldilocks_core.contracts.input_data import DftInputData
from goldilocks_core.contracts.kpoints import KPointSelection
from goldilocks_core.contracts.registry import record_type_id, record_types_by_id
from goldilocks_core.contracts.result import GeneratedFiles
from goldilocks_core.contracts.selection import SelectionRecord

OUTPUT_RECORD_TYPES: tuple[type, ...] = (
    StructureAnalysisRecord,
    ParameterAdvice,
    KPointSelection,
    SelectionRecord,
    GeneratedFiles,
    DftInputData,
)

OUTPUT_TYPES_BY_ID: dict[str, type] = {
    record_type_id(record_type): record_type for record_type in OUTPUT_RECORD_TYPES
}


def resolve_output_types(ids: list[str] | tuple[str, ...]) -> tuple[type, ...]:
    if not ids or any(
        not isinstance(record_id, str) or not record_id.strip() for record_id in ids
    ):
        raise ValueError("outputs must contain at least one record type id")

    normalized = [record_id.strip() for record_id in ids]
    types_by_id = record_types_by_id()
    unknown = [record_id for record_id in normalized if record_id not in types_by_id]
    if unknown:
        available = ", ".join(types_by_id)
        invalid = ", ".join(unknown)
        raise ValueError(
            f"Unknown output record type id(s): {invalid}. Available: {available}"
        )
    return tuple(types_by_id[record_id] for record_id in normalized)
