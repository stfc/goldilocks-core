from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from goldilocks_core.assets.runtime import install as install_assets
from goldilocks_core.assets.store import AssetNotInstalled
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.io.structures import (
    PathStructureSource,
    StructureInputError,
    StructureInspection,
    StructureSource,
    normalize_structure,
)
from goldilocks_core.publication import (
    ArchiveOutput,
    DirectoryOutput,
    OutputTarget,
)
from goldilocks_core.request import ComputeRequest
from goldilocks_core.result import (
    ComputationResult,
    PreparedComputation,
    PublicationUnavailable,
)
from goldilocks_core.runtime.capabilities import Capabilities, build_capabilities
from goldilocks_core.runtime.dispatch import Dispatcher, GraphHandler
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.serialization import to_portable


class OperationFailure(Exception):
    """An expected operation failure, with its stable remote-safe error document.

    Native operations preserve their exceptions. Document operations classify
    only named failures; programming errors are never converted into bad input.
    ``http_status=None`` means the failure has no public HTTP mapping.
    """

    def __init__(self, error: ExpectedFailure | FileExistsError) -> None:
        super().__init__(str(error))
        if isinstance(error, ExpectedFailure):
            self.http_status = {
                "input": 422,
                "dependency": 424,
                "local": None,
            }[error.category]
            self.error = error.public_error()
        else:
            self.http_status = None
            self.error = {"kind": "output_exists", "message": str(error)}

    @classmethod
    def classify(cls, error: Exception) -> OperationFailure | None:
        return (
            cls(error) if isinstance(error, ExpectedFailure | FileExistsError) else None
        )


class Service:
    __slots__ = ("_closed", "_dispatcher", "_owns_runtime", "_runtime")

    def __init__(
        self,
        runtime: Runtime | None = None,
        *,
        task_handlers: tuple[GraphHandler, ...] = (),
    ) -> None:
        self._owns_runtime = runtime is None
        self._runtime = runtime if runtime is not None else Runtime()
        self._dispatcher = Dispatcher(self._runtime)
        for handler in task_handlers:
            self._dispatcher.register(handler)
        self._closed = False

    @property
    def runtime(self) -> Runtime:
        return self._runtime

    @property
    def is_closed(self) -> bool:
        return self._closed

    def compute(
        self,
        request: ComputeRequest,
        *,
        output: OutputTarget | None = None,
    ) -> ComputationResult:
        if output is not None and not isinstance(
            output, DirectoryOutput | ArchiveOutput
        ):
            raise ValueError("output must be a DirectoryOutput, ArchiveOutput, or None")
        self._ensure_open()
        result = self._dispatcher.compute(request)
        return result if output is None else result.publish(output)

    def compute_document(
        self,
        request: ComputeRequest,
        *,
        publication: Literal["memory", "auto", "directory", "archive"] = "memory",
        path: str | Path | None = None,
        prepare_archive: bool = False,
        fetch_missing: bool = False,
    ) -> PreparedComputation:
        """Execute and prepare trusted portable output without transport policy.

        Publication destinations and asset installation are local-only controls;
        remote adapters never expose them in their request documents. Retries
        and their attempt ledger belong to this call, not the shared runtime.
        """
        if publication not in {"memory", "auto", "directory", "archive"}:
            raise ValueError(f"Unknown publication mode: {publication!r}")
        if (publication in {"directory", "archive"}) != (path is not None):
            raise ValueError("Only explicit directory/archive publication takes a path")
        try:
            target = (
                ArchiveOutput(path)
                if publication == "archive"
                else DirectoryOutput(path)
                if publication in {"auto", "directory"}
                else None
            )
        except ValueError as error:
            raise OperationFailure(PublicationUnavailable(str(error))) from error
        attempted: set[tuple[str, str]] = set()
        try:
            while True:
                try:
                    result = self.compute(request, output=target)
                    break
                except AssetNotInstalled as error:
                    key = (error.reference.id, error.reference.version)
                    if not fetch_missing or key in attempted:
                        raise
                    attempted.add(key)
                    install_assets(error.reference.id, store=self._runtime.asset_store)
            return result.prepare(archive=prepare_archive)
        except (ExpectedFailure, FileExistsError) as error:
            raise OperationFailure(error) from error

    def capabilities(self) -> Capabilities:
        self._ensure_open()
        return build_capabilities(self._dispatcher, self._runtime)

    def capabilities_document(self) -> dict[str, Any]:
        try:
            return to_portable(self.capabilities())
        except (ExpectedFailure, FileExistsError) as error:
            raise OperationFailure(error) from error

    def inspect_structure(self, source: StructureSource) -> StructureInspection:
        self._ensure_open()
        return normalize_structure(source).inspection

    def inspect_document(self, source: StructureSource | str | Path) -> dict[str, Any]:
        if isinstance(source, str | Path):
            try:
                source = PathStructureSource(source)
            except ValueError as error:
                raise OperationFailure(StructureInputError(str(error))) from error
        try:
            return to_portable(self.inspect_structure(source))
        except (ExpectedFailure, FileExistsError) as error:
            raise OperationFailure(error) from error

    def close(self) -> None:
        if not self._closed and self._owns_runtime:
            self._runtime.close()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Service is closed.")

    def __enter__(self) -> Service:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def compute(
    request: ComputeRequest,
    *,
    runtime: Runtime | None = None,
    output: OutputTarget | None = None,
) -> ComputationResult:
    """Run one native job, closing only resources created for this call."""
    with Service(runtime) as service:
        return service.compute(request, output=output)
