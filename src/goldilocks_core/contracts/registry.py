from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.contracts.advice import ParameterAdvice
from goldilocks_core.contracts.analysis import StructureAnalysisRecord
from goldilocks_core.contracts.input_data import DftInputData
from goldilocks_core.contracts.kpoints import KPointSelection
from goldilocks_core.contracts.result import GeneratedFiles
from goldilocks_core.contracts.selection import SelectionRecord

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
