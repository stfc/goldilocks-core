from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, get_args

ProvenanceSource = Literal[
    "analysis",
    "user_hint",
    "default",
    "model",
    "lookup",
    "fallback",
]
"""``analysis``: derived from structure facts. ``user_hint``: operator-provided.
``default``: package default when no analysis or hint applies. ``model``: ML
prediction. ``lookup``: resolved from metadata. ``fallback``: no data available."""

JsonDict = dict[str, Any]

PathLike = str | Path

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

KPointShift = tuple[Literal[0, 1], Literal[0, 1], Literal[0, 1]]


Dimensionality = Literal["3d", "2d", "1d", "molecule", "unknown"]

ElectronicCharacter = Literal["metal", "insulator", "likely_metal", "unknown"]
"""``metal``/``insulator``: model-backed. ``likely_metal``: all elements metallic,
not confirmed. ``unknown``: cannot determine from structure alone."""

VdwMethod = Literal["d3", "d3bj", "ts", "mbd"]
"""Code-agnostic labels mapped to code-specific keywords in Generate
(e.g. ``d3bj`` → QE ``vdw_corr='grimme-d3'`` with ``dftd3_version=4``)."""

_VALID_SMEARING_TYPES: frozenset[str] = frozenset(get_args(SmearingType))
_VALID_VDW_METHODS: frozenset[str] = frozenset(get_args(VdwMethod))
