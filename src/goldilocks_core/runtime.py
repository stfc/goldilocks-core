"""Core runtime: model lifecycle owner and task graph dispatch.

The runtime owns the long-lived model backends (kmesh, metallicity) with
explicit load, reuse, reset, and close, and runs registered task graphs. Tasks
register by id and dispatch on ``intent.task``; ``scf_single_point`` is
pre-registered. The runtime builds the SCF run context from a request and its
owned services, then delegates execution to the generic graph executor.

New tasks register their own ``TaskSpec``; the runtime keeps owning models and
dispatching. New model backends become owned services with the same lifecycle
shape as the two below.
"""

from __future__ import annotations

import os
from dataclasses import replace

from pymatgen.core import Structure

from goldilocks_core.advisors import ml_kmesh_advisor
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
from goldilocks_core.graph import TaskSpec, execute
from goldilocks_core.scf import SCF_TASK, ScfContext, assemble_core_result


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

    def __call__(
        self, structure: Structure
    ) -> tuple[ElectronicCharacter, str, float | None]:
        """Classify metallicity, or fall back to the structure heuristic."""
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
        """Drop the cached model so the next call reloads it."""
        self._model = None

    def close(self) -> None:
        """Release model state."""
        self._model = None
        self._graph_settings = None


class CoreRuntime:
    """Own model lifecycle and execute Core task graphs.

    Tasks register by id and dispatch on ``intent.task``; the built-in
    ``scf_single_point`` task is pre-registered. Model backends (kmesh,
    metallicity) are owned services with explicit ``reset``/``close``.
    """

    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
    ) -> None:
        self._registry_path = registry_path or os.environ.get(
            "GOLDILOCKS_MODEL_REGISTRY"
        )
        self._metallicity_checkpoint = metallicity_checkpoint or os.environ.get(
            "GOLDILOCKS_METALLICITY_CHECKPOINT"
        )
        self._metallicity_atom_init = metallicity_atom_init or os.environ.get(
            "GOLDILOCKS_METALLICITY_ATOM_INIT"
        )
        self._backend = self._build_backend()
        self._metallicity = self._build_metallicity()
        self._tasks: dict[str, TaskSpec] = {}
        self.register(SCF_TASK)
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

    def register(self, task_spec: TaskSpec) -> None:
        """Register a task for dispatch by ``intent.task``."""
        self._tasks[task_spec.task] = task_spec

    @property
    def is_closed(self) -> bool:
        """Return whether this runtime has been closed."""
        return self._closed

    def recommend(self, request: CoreJobRequest) -> CoreResult:
        """Execute the task's recommend preset and assemble a full result."""
        self._ensure_open()
        task = self._task_for(request)
        records = execute(
            task, task.preset("recommend").outputs, self._context(request)
        )
        return assemble_core_result(request, records)

    def generate(
        self,
        request: CoreJobRequest,
        *,
        output_dir: str | None = None,
    ) -> CoreResult:
        """Execute the task's generate preset and optionally publish a bundle."""
        self._ensure_open()
        task = self._task_for(request)
        records = execute(task, task.preset("generate").outputs, self._context(request))
        result = assemble_core_result(request, records)
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
        task = self._task_for(request)
        return execute(task, outputs, self._context(request))

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

    def _context(self, request: CoreJobRequest) -> ScfContext:
        """Build a fresh SCF run context from a request and owned services."""
        backend: KMeshAdvisor = self._backend
        if request.kmesh_model is not None:
            backend = ml_kmesh_advisor(request.kmesh_model)
        return ScfContext(
            structure_input=request.structure,
            kmesh_backend=backend,
            metallicity_classifier=self._metallicity,
            intent=request.intent,
            hints=request.hints,
            pseudo_metadata=request.pseudo_metadata,
        )

    def _task_for(self, request: CoreJobRequest) -> TaskSpec:
        """Return the registered task for ``request.intent.task``."""
        task = self._tasks.get(request.intent.task)
        if task is None:
            available = ", ".join(sorted(self._tasks)) or "none"
            raise ValueError(
                f"No Core task registered for task={request.intent.task!r}. "
                f"Available: {available}"
            )
        return task

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("CoreRuntime is closed.")
