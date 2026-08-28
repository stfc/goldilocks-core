from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAliasType

from goldilocks_core.contracts.hints import CalculationHints, CalculationIntent
from goldilocks_core.contracts.models import ModelSpec
from goldilocks_core.contracts.registry import record_type_id
from goldilocks_core.contracts.selection import PseudoMetadata
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.structure import (
    InlineStructureSource,
    InMemoryStructureSource,
    PathStructureSource,
    StructureInspection,
    StructureSource,
)
from goldilocks_core.contracts.types import JsonDict
from goldilocks_core.contracts.validate import _validate_optional_nonempty_str


@dataclass(frozen=True, slots=True)
class RecordSelection:
    records: tuple[type, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple):
            object.__setattr__(self, "records", tuple(self.records))
        if not self.records:
            raise ValueError("RecordSelection.records must not be empty")
        if any(not isinstance(record, type | TypeAliasType) for record in self.records):
            raise ValueError("RecordSelection.records must contain types")

    def to_dict(self) -> JsonDict:
        return {"records": [record_type_id(item) for item in self.records]}


@dataclass(frozen=True, slots=True)
class PresetSelection:
    preset: str

    def __post_init__(self) -> None:
        if not isinstance(self.preset, str) or not self.preset.strip():
            raise ValueError("PresetSelection.preset must be a non-empty string")

    def to_dict(self) -> JsonDict:
        return {"preset": self.preset}


type ComputationSelection = PresetSelection | RecordSelection


def _validate_pseudo_source(
    metadata: tuple[PseudoMetadata, ...] | None,
    root: str | None,
    table: str | None,
    request_type: str,
) -> None:
    if metadata is not None and any(
        not isinstance(item, PseudoMetadata) for item in metadata
    ):
        raise ValueError(f"{request_type}.pseudo_metadata must contain PseudoMetadata")
    if sum((metadata is not None, root is not None, table is not None)) > 1:
        raise ValueError(
            f"{request_type} accepts only one of pseudo_metadata, "
            "pseudo_root, or pseudo_table"
        )


@dataclass(frozen=True, slots=True)
class CalculationDraft:
    """One computation draft: structure, intent, hints, and pseudo source.

    Exactly one pseudopotential source may be set: ``pseudo_metadata``
    (in-memory records), ``pseudo_root`` (operator-managed directory), or
    ``pseudo_table`` (registered asset-store table). All three unset is
    allowed for recommendation and rejected by generation.
    """

    structure: StructureSource | StructureInspection
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_metadata: tuple[PseudoMetadata, ...] | None = None
    pseudo_root: str | None = None
    pseudo_table: str | None = None
    kmesh_model: ModelSpec | None = None

    def __post_init__(self) -> None:
        if self.pseudo_metadata is not None and not isinstance(
            self.pseudo_metadata, tuple
        ):
            object.__setattr__(self, "pseudo_metadata", tuple(self.pseudo_metadata))
        _validate_optional_nonempty_str(
            self.pseudo_root, "CalculationDraft.pseudo_root"
        )
        _validate_optional_nonempty_str(
            self.pseudo_table, "CalculationDraft.pseudo_table"
        )
        _validate_pseudo_source(
            self.pseudo_metadata,
            self.pseudo_root,
            self.pseudo_table,
            "CalculationDraft",
        )

    def to_dict(self) -> JsonDict:
        return {
            "structure": self.structure.to_dict(),
            "intent": to_jsonable(self.intent),
            "hints": to_jsonable(self.hints),
            "pseudo_metadata": (
                [item.to_dict() for item in self.pseudo_metadata]
                if self.pseudo_metadata is not None
                else None
            ),
            "pseudo_root": (
                {"kind": "local_root"} if self.pseudo_root is not None else None
            ),
            "pseudo_table": self.pseudo_table,
            "kmesh_model": (
                self.kmesh_model.to_dict() if self.kmesh_model is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ComputeRequest:
    """One compute job: a draft plus what to run over it.

    ``selection`` is either a named preset or a set of record ids; records
    the selection does not name are not computed.
    """

    draft: CalculationDraft
    selection: ComputationSelection

    def __post_init__(self) -> None:
        if not isinstance(self.draft, CalculationDraft):
            raise ValueError("ComputeRequest.draft must be a CalculationDraft")
        if not isinstance(
            self.draft.structure,
            InlineStructureSource | PathStructureSource | InMemoryStructureSource,
        ):
            raise ValueError(
                "ComputeRequest.draft.structure must be a Structure Source variant"
            )
        if not isinstance(self.selection, PresetSelection | RecordSelection):
            raise ValueError(
                "ComputeRequest.selection must be a PresetSelection or RecordSelection"
            )

    def to_dict(self) -> JsonDict:
        return {
            "draft": self.draft.to_dict(),
            "selection": self.selection.to_dict(),
        }
