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
    """Operator request for a named-preset Core run (recommend/generate).

    Passed to :func:`run_core_job` (or a dispatcher's ``recommend``/``generate``).
    ``mode`` selects the preset; ``output_dir`` is meaningful only with
    ``generate``.

    Attributes:
        structure: structure input — a pymatgen Structure or a path to a
            structure file.
        intent: what to calculate.
        hints: optional operator overrides.
        mode: preset mode: ``recommend`` or ``generate``.
        pseudo_metadata: caller-supplied pseudopotential metadata; when provided
            it takes precedence over filesystem-backed sources.
        pseudo_root: optional operator-managed UPF root.
        pseudo_table: optional exact registered table identifier.
        output_dir: optional output directory, meaningful only with
            ``generate``. The generate entrypoint handles publishing there.
        kmesh_model: optional local k-index model spec; when set, the SCF path
            uses it for k-point selection instead of the default QRF model.
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
        """Validate preset mode and pseudopotential source references."""
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
        """Return a JSON-serializable dictionary."""
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
    """Operator request for an explicit record query.

    Passed to :func:`query_records` (or a dispatcher's ``compute``). ``outputs``
    is required: it names the DAG record types to compute.

    Attributes:
        structure: structure input — a pymatgen Structure or a path to a
            structure file.
        outputs: requested DAG record types (required, non-None).
        intent: what to calculate.
        hints: optional operator overrides.
        pseudo_metadata: caller-supplied metadata, which takes source precedence.
        pseudo_root: optional operator-managed UPF root.
        pseudo_table: optional exact registered table identifier.
        kmesh_model: optional local k-index model spec.
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
        """Validate pseudopotential source references."""
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
        """Return a JSON-serializable dictionary with stable record ids."""
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
