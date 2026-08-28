from __future__ import annotations

from dataclasses import dataclass, field

from goldilocks_core.contracts.hints import CalculationHints, CalculationIntent
from goldilocks_core.contracts.models import ModelSpec
from goldilocks_core.contracts.registry import record_type_id
from goldilocks_core.contracts.selection import PseudoMetadata
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.contracts.types import JobMode, JsonDict, StructureInput
from goldilocks_core.contracts.validate import _validate_optional_nonempty_str


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
class PresetRequest:
    """One complete recommend-or-generate job.

    Exactly one pseudopotential source may be set: ``pseudo_metadata``
    (in-memory records), ``pseudo_root`` (operator-managed directory), or
    ``pseudo_table`` (registered asset-store table). All three unset is
    allowed for recommendation and rejected by generation. ``output_dir``
    publishes a bundle and only applies to generate jobs.
    """

    structure: StructureInput
    intent: CalculationIntent = field(default_factory=CalculationIntent)
    hints: CalculationHints = field(default_factory=CalculationHints)
    mode: JobMode = "recommend"
    pseudo_metadata: tuple[PseudoMetadata, ...] | None = None
    pseudo_root: str | None = None
    pseudo_table: str | None = None
    output_dir: str | None = None
    kmesh_model: ModelSpec | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"recommend", "generate"}:
            raise ValueError(f"Unsupported Core job mode: {self.mode}")
        if self.pseudo_metadata is not None and not isinstance(
            self.pseudo_metadata, tuple
        ):
            object.__setattr__(self, "pseudo_metadata", tuple(self.pseudo_metadata))
        _validate_optional_nonempty_str(self.pseudo_root, "PresetRequest.pseudo_root")
        _validate_optional_nonempty_str(self.pseudo_table, "PresetRequest.pseudo_table")
        _validate_pseudo_source(
            self.pseudo_metadata,
            self.pseudo_root,
            self.pseudo_table,
            "PresetRequest",
        )

    def to_dict(self) -> JsonDict:
        return {
            "structure": to_jsonable(self.structure),
            "intent": to_jsonable(self.intent),
            "hints": to_jsonable(self.hints),
            "mode": self.mode,
            "pseudo_metadata": to_jsonable(self.pseudo_metadata),
            "pseudo_root": self.pseudo_root,
            "pseudo_table": self.pseudo_table,
            "output_dir": self.output_dir,
            "kmesh_model": to_jsonable(self.kmesh_model),
        }


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """One compute job returning only the named record types.

    ``outputs`` names record types resolved through the Core registry.
    Exactly one pseudopotential source may be set: ``pseudo_metadata``,
    ``pseudo_root``, or ``pseudo_table``; all unset is allowed where the
    requested records do not need pseudopotentials.
    """

    structure: StructureInput
    outputs: tuple[type, ...]
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
        _validate_optional_nonempty_str(self.pseudo_root, "QueryRequest.pseudo_root")
        _validate_optional_nonempty_str(self.pseudo_table, "QueryRequest.pseudo_table")
        _validate_pseudo_source(
            self.pseudo_metadata,
            self.pseudo_root,
            self.pseudo_table,
            "QueryRequest",
        )

    def to_dict(self) -> JsonDict:
        return {
            "structure": to_jsonable(self.structure),
            "outputs": [record_type_id(output_type) for output_type in self.outputs],
            "intent": to_jsonable(self.intent),
            "hints": to_jsonable(self.hints),
            "pseudo_metadata": to_jsonable(self.pseudo_metadata),
            "pseudo_root": self.pseudo_root,
            "pseudo_table": self.pseudo_table,
            "kmesh_model": to_jsonable(self.kmesh_model),
        }
