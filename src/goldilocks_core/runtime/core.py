"""Core runtime: model lifecycle owner.

Owns the long-lived model backends (kmesh, metallicity) with explicit load,
reuse, reset, and close, and exposes them as read-only services for task
handlers to read. The runtime holds no task registry and runs no graphs —
that is :class:`~goldilocks_core.runtime.dispatch.TaskDispatcher`'s job. New
model backends become owned services with the same lifecycle shape as the
two below.
"""

from __future__ import annotations

import os

from pymatgen.core import Structure

from goldilocks_core.advisors.kdistance_advisor import QrfKDistanceBackend
from goldilocks_core.analysis import heuristic_metallicity
from goldilocks_core.contracts import (
    ElectronicCharacter,
    KMeshService,
    ModelSpec,
    PathLike,
)


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
    """Own the lifecycle of the kmesh and metallicity model services.

    Exposes ``kmesh_service`` and ``metallicity`` as read-only services for
    task handlers, and owns their ``reset``/``close``. Holds no task registry
    and dispatches no graphs — use
    :class:`~goldilocks_core.runtime.dispatch.TaskDispatcher` for that.
    """

    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
        kmesh_service: KMeshService | None = None,
    ) -> None:
        self._registry_path = registry_path
        self._metallicity_checkpoint = metallicity_checkpoint
        self._metallicity_atom_init = metallicity_atom_init
        self._backend = (
            kmesh_service if kmesh_service is not None else self._build_backend()
        )
        self._metallicity = self._build_metallicity()
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

    @property
    def kmesh_service(self) -> KMeshService:
        """The runtime-owned kmesh service."""
        return self._backend

    @property
    def metallicity(self) -> MetallicityService:
        """The runtime-owned metallicity classifier."""
        return self._metallicity

    def describe_models(self) -> list[dict[str, str | None]]:
        """Return transport-safe descriptions of all registered ML models.

        Lists every model in the runtime's registry: the default QRF k-distance
        model and the CGCNN metallicity classifier it depends on. Local models
        supplied per-request via ``kmesh_model`` are not listed here.
        """
        from goldilocks_core.ml.model_registry import load_default_qrf_config

        config = load_default_qrf_config(self._registry_path)
        return [
            _model_spec_to_dict(config.model),
            _model_spec_to_dict(config.metallicity_model),
        ]

    @property
    def is_closed(self) -> bool:
        """Return whether this runtime has been closed."""
        return self._closed

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


def _model_spec_to_dict(spec: ModelSpec) -> dict[str, str | None]:
    """Serialize a ModelSpec to a transport-safe dictionary."""
    return {
        "name": spec.name,
        "version": spec.version,
        "model_type": spec.model_type,
        "target": spec.target,
        "feature_set": spec.feature_set,
        "source": spec.source,
        "location": spec.location,
        "revision": spec.revision,
    }
