"""Core runtime: model lifecycle owner and task graph dispatch.

The runtime owns the long-lived model backends (kmesh, metallicity) with
explicit load, reuse, reset, and close, and dispatches registered task graphs.
Tasks register a :class:`TaskHandler` (graph + context builder + result
assembler) and dispatch on ``intent.task``; the SCF task is pre-registered. The
runtime hands a request and itself to the handler's context builder and the
resulting records to the handler's assembler, so it imports no task-specific
code on the dispatch path.

New tasks register their own ``TaskHandler``; the runtime keeps owning models
and dispatching. New model backends become owned services with the same
lifecycle shape as the two below.
"""

from __future__ import annotations

import os
from dataclasses import replace

from pymatgen.core import Structure

from goldilocks_core.advisors.kdistance_advisor import QrfKDistanceBackend
from goldilocks_core.analysis import heuristic_metallicity
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    CoreJobRequest,
    CoreRecords,
    CoreResult,
    ElectronicCharacter,
    KMeshAdvisor,
    PathLike,
)
from goldilocks_core.runtime.graph import execute
from goldilocks_core.runtime.scf import SCF_HANDLER
from goldilocks_core.runtime.task import TaskHandler


class MetallicityService:
    """Runtime-owned CGCNN metallicity classifier with model lifecycle.

    Returns the structure-only heuristic when no model artifacts are
    configured. Otherwise lazy-loads the model and graph settings once, reuses
    them across calls, and drops them on reset/close. Symmetric with the kmesh
    backend: a callable service the runtime owns and resets.
    """

    __slots__ = (
        "_checkpoint",
        "_atom_init",
        "_registry_path",
        "_model",
        "_graph_settings",
        "_closed",
    )

    def __init__(
        self,
        *,
        checkpoint: PathLike | None,
        atom_init: PathLike | None,
        registry_path: PathLike | None,
    ) -> None:
        self._checkpoint = checkpoint
        self._atom_init = atom_init
        self._registry_path = registry_path
        self._model: object | None = None
        self._graph_settings: tuple[float, int] | None = None
        self._closed = False

    def __call__(
        self, structure: Structure
    ) -> tuple[ElectronicCharacter, str, float | None]:
        """Classify metallicity, or fall back to the structure heuristic."""
        if self._closed:
            raise RuntimeError("MetallicityService is closed.")
        if self._checkpoint is None or self._atom_init is None:
            return heuristic_metallicity(structure), "heuristic", None

        from goldilocks_core.ml.qrf.metallicity import (
            classify_metallicity,
            load_metallicity_model,
        )

        if self._model is None:
            self._model = load_metallicity_model(os.fspath(self._checkpoint))
        if self._graph_settings is None:
            from goldilocks_core.ml.model_registry import load_default_qrf_config

            settings = load_default_qrf_config(self._registry_path).feature_settings
            self._graph_settings = (
                settings.metallicity_graph_radius,
                settings.metallicity_max_neighbors,
            )
        graph_radius, max_neighbors = self._graph_settings
        character, confidence = classify_metallicity(
            structure,
            self._model,
            os.fspath(self._atom_init),
            graph_radius=graph_radius,
            max_neighbors=max_neighbors,
        )
        return character, "model", confidence

    def reset(self) -> None:
        """Drop the cached model; graph settings persist across reset."""
        self._model = None

    def close(self) -> None:
        """Release model state."""
        self._model = None
        self._graph_settings = None
        self._closed = True


class CoreRuntime:
    """Own model lifecycle and execute Core task graphs.

    Tasks register a :class:`TaskHandler` and dispatch on ``intent.task``; the
    built-in ``scf_single_point`` task is pre-registered. Model backends
    (kmesh, metallicity) are owned services with explicit ``reset``/``close``.
    """

    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
        kmesh_backend: KMeshAdvisor | None = None,
    ) -> None:
        self._registry_path = registry_path
        self._metallicity_checkpoint = metallicity_checkpoint
        self._metallicity_atom_init = metallicity_atom_init
        self._backend = (
            kmesh_backend if kmesh_backend is not None else self._build_backend()
        )
        self._metallicity = self._build_metallicity()
        self._tasks: dict[str, TaskHandler] = {}
        self.register(SCF_HANDLER)
        self._closed = False

    def _build_backend(self) -> QrfKDistanceBackend:
        """Build the runtime-owned QRF kmesh backend."""
        return QrfKDistanceBackend(
            registry_path=self._registry_path,
            metallicity_checkpoint=self._metallicity_checkpoint,
            metallicity_atom_init=self._metallicity_atom_init,
        )

    def _build_metallicity(self) -> MetallicityService:
        """Build the runtime-owned metallicity classifier."""
        return MetallicityService(
            checkpoint=self._metallicity_checkpoint,
            atom_init=self._metallicity_atom_init,
            registry_path=self._registry_path,
        )

    def register(self, handler: TaskHandler) -> None:
        """Register a task for dispatch by ``intent.task``."""
        self._tasks[handler.spec.task] = handler

    @property
    def kmesh_backend(self) -> KMeshAdvisor:
        """The runtime-owned kmesh backend."""
        return self._backend

    @property
    def metallicity(self) -> MetallicityService:
        """The runtime-owned metallicity classifier."""
        return self._metallicity

    @property
    def is_closed(self) -> bool:
        """Return whether this runtime has been closed."""
        return self._closed

    def recommend(self, request: CoreJobRequest) -> CoreResult:
        """Execute the task's recommend preset and assemble a full result."""
        self._ensure_open()
        handler = self._handler_for(request)
        task = handler.spec
        records = execute(
            task,
            task.preset("recommend").outputs,
            handler.build_context(request, self),
        )
        return handler.assemble_result(request, records)

    def generate(
        self,
        request: CoreJobRequest,
        *,
        output_dir: str | None = None,
    ) -> CoreResult:
        """Execute the task's generate preset and optionally publish a bundle."""
        self._ensure_open()
        handler = self._handler_for(request)
        task = handler.spec
        records = execute(
            task,
            task.preset("generate").outputs,
            handler.build_context(request, self),
        )
        result = handler.assemble_result(request, records)
        if output_dir is None:
            return result
        return replace(result, bundle=write_bundle_directory(result, output_dir))

    def compute(
        self,
        outputs: tuple[type, ...],
        request: CoreJobRequest,
    ) -> CoreRecords:
        """Execute the minimal subgraph for ``outputs`` on ``request``'s task."""
        self._ensure_open()
        handler = self._handler_for(request)
        return execute(handler.spec, outputs, handler.build_context(request, self))

    def reset(self) -> None:
        """Discard cached model state so the next model call reloads it."""
        self._backend.reset()
        self._metallicity.reset()

    def close(self) -> None:
        """Release model resources; repeated calls are harmless."""
        if self._closed:
            return
        self._backend.close()
        self._metallicity.close()
        self._closed = True

    def __enter__(self) -> CoreRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _handler_for(self, request: CoreJobRequest) -> TaskHandler:
        """Return the registered handler for ``request.intent.task``."""
        handler = self._tasks.get(request.intent.task)
        if handler is None:
            available = ", ".join(sorted(self._tasks)) or "none"
            raise ValueError(
                f"No Core task registered for task={request.intent.task!r}. "
                f"Available: {available}"
            )
        return handler

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("CoreRuntime is closed.")
