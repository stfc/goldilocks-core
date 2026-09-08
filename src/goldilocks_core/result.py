from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.input_data import DftInputData, input_data_portable
from goldilocks_core.publication import (
    DirectoryOutput,
    OutputTarget,
    Publication,
    Publisher,
)
from goldilocks_core.request import CalculationDraft, ComputationSelection
from goldilocks_core.selection import SelectionRecord, selection_portable
from goldilocks_core.serialization import to_jsonable, to_portable
from goldilocks_core.types import JsonDict


class PublicationUnavailable(ExpectedFailure, ValueError):
    """The selected record set cannot satisfy an explicit publication request."""

    kind = "publication_unavailable"
    category = "local"


@dataclass(frozen=True, slots=True)
class ComputationResult:
    """Complete record set from one Compute call.

    ``records`` holds every computed record for the requested selection;
    ``warnings`` aggregates every stage's warnings and is the authoritative
    place to check for incomplete or degraded results. ``publication`` is
    set only when the request named an output target.
    """

    draft: CalculationDraft
    task: str
    task_revision: str
    selection: ComputationSelection
    records: dict[type, Any]
    warnings: tuple[str, ...] = ()
    publication: Publication | None = None
    schema_version: Literal[1] = field(default=1, init=False)

    def publish(self, output: OutputTarget) -> ComputationResult:
        """Publish only the immutable material captured in this computation."""
        input_data = self.records.get(DftInputData)
        if input_data is None:
            if isinstance(output, DirectoryOutput) and output.path is None:
                return self
            raise PublicationUnavailable(
                "The Computation Result does not contain DFT Input Data to publish"
            )
        return replace(self, publication=Publisher().publish(input_data, output))

    def prepare(self, *, archive: bool = False) -> PreparedComputation:
        """Prepare portable records and an optional archive from the same snapshot."""
        input_data = self.records.get(DftInputData)
        archive_bytes = (
            Publisher().archive_bytes(input_data)
            if archive and input_data is not None
            else None
        )
        return PreparedComputation(to_portable(self), archive_bytes)


@dataclass(frozen=True, slots=True)
class PreparedComputation:
    """Portable records and the optional archive of those exact computed inputs."""

    result: JsonDict
    archive: bytes | None = None


@to_portable.register(ComputationResult)
def _computation_result_portable(result: ComputationResult) -> JsonDict:
    from goldilocks_core.runtime.registry import record_type_id

    records = {}
    for record_type, value in result.records.items():
        record_id = record_type_id(record_type)
        if record_type is SelectionRecord:
            records[record_id] = selection_portable(value)
        elif record_type is DftInputData:
            records[record_id] = input_data_portable(value)
        else:
            records[record_id] = to_portable(value)
    return {
        "schema_version": result.schema_version,
        "draft": to_portable(result.draft),
        "task": result.task,
        "task_revision": result.task_revision,
        "selection": to_portable(result.selection),
        "records": records,
        "warnings": list(result.warnings),
        "publication": to_jsonable(result.publication),
    }
