from __future__ import annotations

from pymatgen.core import Structure

from goldilocks_core.contracts.advice import ParameterAdvice
from goldilocks_core.contracts.analysis import StructureAnalysisRecord
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
}


def record_type_id(record_type: type) -> str:
    try:
        return RECORD_TYPE_IDS[record_type]
    except KeyError as error:
        raise ValueError(
            f"No stable transport record id for record type {record_type.__name__}"
        ) from error
