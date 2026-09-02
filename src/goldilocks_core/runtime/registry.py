from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.input_data import DftInputData
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.selection import SelectionRecord

RECORD_TYPE_IDS: dict[type, str] = {
    Structure: "structure",
    StructureAnalysisRecord: "analysis",
    ParameterAdvice: "advice",
    KPointSelection: "k_points",
    SelectionRecord: "selection",
    GeneratedFiles: "generated_files",
    DftInputData: "dft_input_data",
}


def register_record_types(record_ids: tuple[tuple[type, str], ...]) -> None:
    proposed = dict(RECORD_TYPE_IDS)
    types_by_id = {
        record_id: record_type for record_type, record_id in proposed.items()
    }
    for record_type, record_id in record_ids:
        existing_id = proposed.get(record_type)
        if existing_id is not None and existing_id != record_id:
            raise ValueError(
                f"Record type {record_type.__name__} is already registered as "
                f"{existing_id!r}"
            )
        existing_type = types_by_id.get(record_id)
        if existing_type is not None and existing_type is not record_type:
            raise ValueError(
                f"Record id {record_id!r} is already registered for "
                f"{existing_type.__name__}"
            )
        proposed[record_type] = record_id
        types_by_id[record_id] = record_type
    RECORD_TYPE_IDS.update(proposed)


def record_types_by_id() -> dict[str, type]:
    return {
        record_id: record_type for record_type, record_id in RECORD_TYPE_IDS.items()
    }


def record_type_id(record_type: type) -> str:
    try:
        return RECORD_TYPE_IDS[record_type]
    except KeyError as error:
        raise ValueError(
            f"No stable transport record id for record type {record_type.__name__}"
        ) from error


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
