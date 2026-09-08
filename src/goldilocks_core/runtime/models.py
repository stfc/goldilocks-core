from __future__ import annotations

import os
from threading import Lock

from pymatgen.core import Structure

from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.analysis import heuristic_metallicity
from goldilocks_core.assets import AssetNotInstalled, AssetStore
from goldilocks_core.contracts import (
    ElectronicCharacter,
    KMeshService,
    ModelSpec,
    PathLike,
)
from goldilocks_core.ml.model_registry import QrfKpointsConfig


class MetallicityModel:
    __slots__ = (
        "_checkpoint",
        "_atom_init",
        "_registry_path",
        "_asset_store",
        "_model",
        "_config",
        "_load_lock",
        "_closed",
    )

    def __init__(
        self,
        *,
        checkpoint: PathLike | None,
        atom_init: PathLike | None,
        registry_path: PathLike | None,
        asset_store: AssetStore,
    ) -> None:
        self._checkpoint = checkpoint
        self._atom_init = atom_init
        self._registry_path = registry_path
        self._asset_store = asset_store
        self._model: object | None = None
        self._config = None
        self._closed = False
        self._load_lock = Lock()

    def __call__(
        self, structure: Structure
    ) -> tuple[ElectronicCharacter, str, float | None]:
        with self._load_lock:
            if self._closed:
                raise RuntimeError("MetallicityModel is closed.")
            if not structure.is_ordered:
                return heuristic_metallicity(structure), "heuristic", None
            from goldilocks_core.ml.model_registry import load_default_qrf_config
            from goldilocks_core.ml.qrf.metallicity import (
                classify_metallicity,
                load_metallicity_model,
            )

            if self._config is None:
                self._config = load_default_qrf_config(self._registry_path)
            config = self._config
            if self._checkpoint is None or self._atom_init is None:
                if config.metallicity_asset is None:
                    return heuristic_metallicity(structure), "heuristic", None
                try:
                    installed = self._asset_store.resolve_spec(config.metallicity_asset)
                except AssetNotInstalled:
                    return heuristic_metallicity(structure), "heuristic", None
                self._checkpoint = installed.path(config.metallicity_checkpoint_file)
                self._atom_init = installed.path(config.metallicity_atom_init_file)
            if self._model is None:
                self._model = load_metallicity_model(os.fspath(self._checkpoint))
            model = self._model
            atom_init = os.fspath(self._atom_init)
            settings = config.feature_settings

        character, confidence = classify_metallicity(
            structure,
            model,
            atom_init,
            graph_radius=settings.metallicity_graph_radius,
            max_neighbors=settings.metallicity_max_neighbors,
        )
        return character, "model", confidence

    @property
    def loaded_config(self) -> QrfKpointsConfig | None:
        """Registry snapshot belonging to the loaded classifier."""
        return self._config if self._model is not None else None

    def reset(self) -> None:
        with self._load_lock:
            self._model = None

    def close(self) -> None:
        with self._load_lock:
            self._model = None
            self._closed = True


class Runtime:
    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
        metallicity_model: ModelSpec | None = None,
        kmesh_service: KMeshService | None = None,
        asset_store: AssetStore | None = None,
        pseudo_registry_path: PathLike | None = None,
    ) -> None:
        configured = (
            metallicity_checkpoint is not None,
            metallicity_atom_init is not None,
            metallicity_model is not None,
        )
        if any(configured) != all(configured):
            raise ValueError(
                "metallicity_checkpoint, metallicity_atom_init, and "
                "metallicity_model must be configured together"
            )
        self._registry_path = registry_path
        self._metallicity_model_spec = metallicity_model
        self._asset_store = asset_store or AssetStore()
        self._pseudo_registry_path = pseudo_registry_path
        self._uses_default_kmesh_model = kmesh_service is None
        self._backend = (
            kmesh_service
            if kmesh_service is not None
            else QrfBackend(
                registry_path=registry_path,
                metallicity_checkpoint=metallicity_checkpoint,
                metallicity_atom_init=metallicity_atom_init,
                asset_store=self._asset_store,
            )
        )
        self._metallicity = MetallicityModel(
            checkpoint=metallicity_checkpoint,
            atom_init=metallicity_atom_init,
            registry_path=registry_path,
            asset_store=self._asset_store,
        )
        self._closed = False

    @property
    def kmesh_service(self) -> KMeshService:
        return self._backend

    @property
    def uses_default_kmesh_model(self) -> bool:
        return self._uses_default_kmesh_model

    @property
    def loaded_kmesh_config(self) -> QrfKpointsConfig | None:
        if self._uses_default_kmesh_model and isinstance(self._backend, QrfBackend):
            return self._backend.loaded_config
        return None

    @property
    def metallicity_model_spec(self) -> ModelSpec | None:
        return self._metallicity_model_spec

    @property
    def uses_default_metallicity_model(self) -> bool:
        return self._metallicity_model_spec is None

    @property
    def metallicity(self) -> MetallicityModel:
        return self._metallicity

    @property
    def asset_store(self) -> AssetStore:
        return self._asset_store

    @property
    def pseudo_registry_path(self) -> PathLike | None:
        return self._pseudo_registry_path

    @property
    def model_registry_path(self) -> PathLike | None:
        return self._registry_path

    def describe_models(self) -> list[dict[str, str | None]]:
        from goldilocks_core.ml.model_registry import load_default_qrf_config

        config = load_default_qrf_config(self._registry_path)
        return [
            _model_spec_to_dict(config.model),
            _model_spec_to_dict(config.metallicity_model),
        ]

    @property
    def is_closed(self) -> bool:
        return self._closed

    def reset(self) -> None:
        self._backend.reset()
        self._metallicity.reset()

    def close(self) -> None:
        if self._closed:
            return
        self._backend.close()
        self._metallicity.close()
        self._closed = True

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _model_spec_to_dict(spec: ModelSpec) -> dict[str, str | None]:
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
