from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from goldilocks_core.contracts.advice import ParameterAdvice
from goldilocks_core.contracts.analysis import StructureAnalysisRecord
from goldilocks_core.contracts.hints import CalculationIntent
from goldilocks_core.contracts.kpoints import KPointSelection
from goldilocks_core.contracts.selection import SelectionRecord
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JsonDict


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Generated text file content for a target DFT code.

    Bundle writers interpret ``path`` relative to their output directory and
    must reject paths that escape it.

    Attributes:
        path: relative file path within the bundle (e.g.
            ``inputs/qe.in``).
        content: full text content of the generated file.
        role: file role (e.g. ``input``, ``output``). Currently
            always ``input``.
    """

    path: str
    content: str
    role: str = "input"

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


type GeneratedFiles = tuple[GeneratedFile, ...]


@dataclass(frozen=True, slots=True)
class BundleRecord:
    """Bundle publication output: where files were written and the manifest.

    It is populated when generate publishes files to an output directory.

    Attributes:
        path: bundle root directory path.
        manifest: bundle manifest dictionary.
    """

    path: str
    manifest: JsonDict

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)


class Records(Mapping[type, Any]):
    """Requested DAG records keyed by their record types.

    Only explicitly requested record types are present.
    """

    __slots__ = ("_records",)

    def __init__(self, records: Mapping[type, Any] | None = None) -> None:
        self._records = dict(records or {})

    def __getitem__(self, record_type: type) -> Any:
        return self._records[record_type]

    def __iter__(self) -> Iterator[type]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def to_dict(self) -> JsonDict:
        """Return records as a JSON-serializable dictionary keyed by stable ids."""
        from goldilocks_core.contracts.registry import record_type_id

        return to_jsonable(
            {
                record_type_id(record_type): record
                for record_type, record in self._records.items()
            }
        )


@dataclass(frozen=True, slots=True)
class Result:
    """Records produced by a recommendation or generation workflow.

    Scientific records are populated as their stages run. ``k_points`` is the
    Kmesh-stage output alongside the Select-stage pseudopotentials.
    ``generated_files`` is populated in generate mode. ``bundle`` is set only
    when generate is given an output directory. The request is not echoed here
    — the caller already has it; CLI/HTTP layers echo it themselves.

    Attributes:
        intent: what the operator asked for.
        analysis: structure facts from the Analyze stage.
        advice: provenance-backed recommendations from the Advise
            stage.
        k_points: concrete grid and shift from the Kmesh stage.
        selection: concrete pseudopotentials from the Select stage.
        generated_files: generated input files, populated by Generate mode.
        warnings: aggregated warnings from analysis, Kmesh, and
            selection.
        bundle: output bundle record, set only when generate writes files.
    """

    intent: CalculationIntent
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    k_points: KPointSelection
    selection: SelectionRecord
    generated_files: GeneratedFiles = ()
    warnings: tuple[str, ...] = ()
    bundle: BundleRecord | None = None

    def to_dict(self) -> JsonDict:
        """Return a JSON-serializable dictionary."""
        return to_jsonable(self)
