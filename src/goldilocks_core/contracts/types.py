"""Literal and typing aliases shared across the contract catalogue."""

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
"""Origin of a scientific recommendation or selection.

- ``analysis``: derived from structure facts (e.g. heavy elements → SOC consideration).
- ``user_hint``: explicitly provided by the operator via ``CalculationHints``.
- ``default``: package-level default when no analysis or hint applies.
- ``model``: ML model prediction (e.g. k-index from the CSLR advisor).
- ``lookup``: resolved from supplied metadata (e.g. pseudo selection from a registry).
- ``fallback``: no matching data was available; the value is a placeholder.
"""

JsonDict = dict[str, Any]
"""JSON-serializable dictionary type."""

PathLike = str | Path
"""String or path-like object accepted as a file location."""

StructureInput = Structure | PathLike
"""Structure input: a pymatgen ``Structure`` or a path to a structure file."""

TaskId = str
"""Stable, transport-safe identifier for a Core task."""

StageId = str
"""Stable, transport-safe identifier for a graph stage."""

RecordId = str
"""Stable, transport-safe identifier for a graph record type."""

CodeName = str
"""Target DFT code name."""

CalcTask = str
"""Calculation task name."""

SmearingType = Literal["fixed", "gaussian", "mp", "cold"]
"""Canonical occupation schemes supported by the current QE target."""

ModelSource = Literal["huggingface", "local"]
"""Where a trained model or supporting artifact is resolved from."""

ModelType = Literal["random_forest", "cgcnn", "xgboost"]
"""ML model architecture. Only ``random_forest`` is currently supported."""

KPointGrid = tuple[int, int, int]
"""Uniform immutable k-point mesh as (nk1, nk2, nk3)."""

KPointShift = tuple[int, int, int]
"""Immutable Monkhorst-Pack shift as (s1, s2, s3) with values 0 or 1."""

JobMode = Literal["recommend", "generate"]
"""How far the fixed Core pipeline runs.

- ``recommend``: Load → Analyze → Advise → Kmesh → Select.
- ``generate``: … → Generate, optionally publishing to ``output_dir``.
"""

Dimensionality = Literal["3d", "2d", "1d", "molecule", "unknown"]
"""Bonded-structure dimensionality, or ``unknown`` when detection fails."""

ElectronicCharacter = Literal["metal", "insulator", "likely_metal", "unknown"]
"""Electronic-character classification from a model or structure facts.

- ``metal`` / ``insulator``: model-backed classifications.
- ``likely_metal``: all elements are metallic; treat as likely, not confirmed.
- ``unknown``: cannot determine from structure alone; verify manually.
"""

VdwMethod = Literal["d3", "d3bj", "ts", "mbd"]
"""Code-agnostic van der Waals dispersion method label.

Translated to code-specific keywords in the Generate stage (e.g. ``d3bj`` →
QE ``vdw_corr='grimme-d3'`` with ``dftd3_version=4``).
"""

_VALID_SMEARING_TYPES: frozenset[str] = frozenset(get_args(SmearingType))
_VALID_VDW_METHODS: frozenset[str] = frozenset(get_args(VdwMethod))
