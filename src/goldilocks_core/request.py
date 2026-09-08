from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAliasType, TypedDict

from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.io.structures import (
    InlineStructureSource,
    InMemoryStructureSource,
    NormalizedStructure,
    PathStructureSource,
    StructureInspection,
    StructureSource,
)
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.source import PseudoResolution
from goldilocks_core.runtime.models import ModelResolution, Runtime
from goldilocks_core.serialization import Portable, to_jsonable, to_portable
from goldilocks_core.types import JsonDict
from goldilocks_core.validation import validate_optional_nonempty_str


@dataclass(frozen=True, slots=True)
class RecordSelection:
    records: Annotated[tuple[type, ...], Portable(list[str])]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple):
            object.__setattr__(self, "records", tuple(self.records))
        if not self.records:
            raise ValueError("RecordSelection.records must not be empty")
        if any(not isinstance(record, type | TypeAliasType) for record in self.records):
            raise ValueError("RecordSelection.records must contain types")

    @classmethod
    def from_ids(cls, records: list[str] | tuple[str, ...]) -> RecordSelection:
        # Registration depends on the native request graph; resolve after import.
        from goldilocks_core.runtime.registry import resolve_output_types

        return cls(resolve_output_types(records))


@to_portable.register(RecordSelection)
def _record_selection_portable(selection: RecordSelection) -> JsonDict:
    from goldilocks_core.runtime.registry import record_type_id

    return {"records": [record_type_id(item) for item in selection.records]}


@dataclass(frozen=True, slots=True)
class PresetSelection:
    preset: str

    def __post_init__(self) -> None:
        if not isinstance(self.preset, str) or not self.preset.strip():
            raise ValueError("PresetSelection.preset must be a non-empty string")


@to_portable.register(PresetSelection)
def _preset_selection_portable(selection: PresetSelection) -> JsonDict:
    return {"preset": selection.preset}


type ComputationSelection = PresetSelection | RecordSelection


class LocalPseudoRoot(TypedDict):
    kind: Literal["local_root"]


@dataclass(frozen=True, slots=True)
class CalculationDraft:
    """One computation draft: structure, intent, hints, and pseudo source.

    Exactly one pseudopotential source may be set: ``pseudo_metadata``
    (in-memory records), ``pseudo_root`` (operator-managed directory), or
    ``pseudo_table`` (registered asset-store table). All three unset is
    allowed for recommendation and rejected by generation.
    """

    structure: Annotated[
        StructureSource | StructureInspection, Portable(StructureInspection)
    ]
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    pseudo_metadata: tuple[PseudoMetadata, ...] | None = None
    pseudo_root: Annotated[str | None, Portable(LocalPseudoRoot | None)] = None
    pseudo_table: str | None = None
    kmesh_model: ModelSpec | None = None

    def __post_init__(self) -> None:
        if self.pseudo_metadata is not None:
            object.__setattr__(self, "pseudo_metadata", tuple(self.pseudo_metadata))
        validate_optional_nonempty_str(self.pseudo_root, "CalculationDraft.pseudo_root")
        validate_optional_nonempty_str(
            self.pseudo_table, "CalculationDraft.pseudo_table"
        )
        if self.pseudo_metadata is not None and any(
            not isinstance(item, PseudoMetadata) for item in self.pseudo_metadata
        ):
            raise ValueError(
                "CalculationDraft.pseudo_metadata must contain PseudoMetadata"
            )
        if (
            sum(
                source is not None
                for source in (
                    self.pseudo_metadata,
                    self.pseudo_root,
                    self.pseudo_table,
                )
            )
            > 1
        ):
            raise ValueError(
                "CalculationDraft accepts only one of pseudo_metadata, "
                "pseudo_root, or pseudo_table"
            )


@to_portable.register(CalculationDraft)
def _calculation_draft_portable(draft: CalculationDraft) -> JsonDict:
    return {
        "structure": to_portable(draft.structure),
        "intent": to_jsonable(draft.intent),
        "hints": to_jsonable(draft.hints),
        "pseudo_metadata": (
            [to_portable(item) for item in draft.pseudo_metadata]
            if draft.pseudo_metadata is not None
            else None
        ),
        "pseudo_root": (
            {"kind": "local_root"} if draft.pseudo_root is not None else None
        ),
        "pseudo_table": draft.pseudo_table,
        "kmesh_model": (
            to_portable(draft.kmesh_model) if draft.kmesh_model is not None else None
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

    @classmethod
    def from_local(
        cls,
        structure: str | Path,
        *,
        preset: str | None = None,
        records: list[str] | tuple[str, ...] | None = None,
        intent: dict[str, Any] | None = None,
        hints: dict[str, Any] | None = None,
        pseudo_root: str | Path | None = None,
        pseudo_table: str | None = None,
        model: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> ComputeRequest:
        """Construct a local job using native validation and registered record IDs.

        Unlike remote documents, local jobs may name operator-managed pseudo
        directories and model artifacts. Defaults and invariants remain owned
        by the native intent, hints, draft and selection records.
        """
        if (preset is None) == (records is None):
            raise ValueError("Supply exactly one of preset or records")
        if model is None and (model_name is not None or model_version is not None):
            raise ValueError("Model name and version require a local model")
        return cls(
            CalculationDraft(
                structure=PathStructureSource(structure),
                intent=CalculationIntent(**(intent or {})),
                hints=CalculationHints(**(hints or {})),
                pseudo_root=(
                    str(Path(pseudo_root).expanduser())
                    if pseudo_root is not None
                    else None
                ),
                pseudo_table=pseudo_table,
                kmesh_model=(
                    ModelSpec(
                        name=model_name or "cli-kmesh-model",
                        version=model_version or "unknown",
                        model_type="random_forest",
                        target="k_index",
                        feature_set="cslr",
                        source="local",
                        location=model,
                    )
                    if model is not None
                    else None
                ),
            ),
            PresetSelection(preset)
            if preset is not None
            else RecordSelection.from_ids(records),
        )


@to_portable.register(ComputeRequest)
def _compute_request_portable(request: ComputeRequest) -> JsonDict:
    return {
        "draft": to_portable(request.draft),
        "selection": to_portable(request.selection),
    }


class CalculationResources:
    """Prepare one native request's sources and services without executing it."""

    def __init__(
        self,
        request: ComputeRequest,
        normalized_structure: NormalizedStructure,
        runtime: Runtime,
    ) -> None:
        self.normalized_structure = normalized_structure
        self.draft = request.draft
        self.models = ModelResolution(runtime, self.draft.kmesh_model)
        self.pseudopotentials = PseudoResolution(
            metadata=self.draft.pseudo_metadata,
            root=self.draft.pseudo_root,
            table_id=self.draft.pseudo_table,
            store=runtime.asset_store,
            registry_path=runtime.pseudo_registry_path,
        )
