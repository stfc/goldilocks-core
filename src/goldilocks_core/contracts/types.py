from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args

from pymatgen.core import Structure

ProvenanceSource = Literal[
    "analysis",
    "user_hint",
    "default",
    "model",
    "lookup",
    "fallback",
]

JsonDict = dict[str, Any]

PathLike = str | Path

StructureInput = Structure | PathLike

TaskId = str

StageId = str

RecordId = str

CodeName = str

CalcTask = str

SmearingType = Literal["fixed", "gaussian", "mp", "cold"]

ModelSource = Literal["huggingface", "local"]

ModelType = Literal["random_forest", "cgcnn", "xgboost"]

PseudoAccuracy = Literal["efficiency", "precision"]

PseudoType = Literal["NC", "USPP", "PAW"]

RelativisticTreatment = Literal["scalar", "full", "non-relativistic"]

KPointGrid = tuple[int, int, int]

KPointShift = tuple[int, int, int]

JobMode = Literal["recommend", "generate"]

Dimensionality = Literal["3d", "2d", "1d", "molecule", "unknown"]

ElectronicCharacter = Literal["metal", "insulator", "likely_metal", "unknown"]

VdwMethod = Literal["d3", "d3bj", "ts", "mbd"]

_VALID_SMEARING_TYPES: frozenset[str] = frozenset(get_args(SmearingType))
_VALID_VDW_METHODS: frozenset[str] = frozenset(get_args(VdwMethod))
