from __future__ import annotations

import os
from threading import Lock
from typing import Protocol, runtime_checkable

from pymatgen.core import Structure

from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.analysis import heuristic_metallicity
from goldilocks_core.assets.store import AssetNotInstalled, AssetStore
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.types import ElectronicCharacter, PathLike


@runtime_checkable
class KMeshService(Protocol):
    def __call__(self, structure: Structure) -> KPointSelection: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


class MetallicityModel:
    __slots__ = (
        "_asset_store",
        "_atom_init",
        "_checkpoint",
        "_closed",
        "_graph_settings",
        "_load_lock",
        "_model",
        "_registry_path",
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
        self._graph_settings: tuple[float, int] | None = None
        self._closed = False
        self._load_lock = Lock()

    def __call__(
        self, structure: Structure
    ) -> tuple[ElectronicCharacter, str, float | None]:
        if self._closed:
            raise RuntimeError("MetallicityModel is closed.")
        if not structure.is_ordered:
            return heuristic_metallicity(structure), "heuristic", None

        from goldilocks_core.ml.qrf.metallicity import (
            classify_metallicity,
            load_metallicity_model,
        )

        with self._load_lock:
            missing_artifacts = self._checkpoint is None or self._atom_init is None
            if missing_artifacts and not self._resolve_default_artifacts():
                return heuristic_metallicity(structure), "heuristic", None
            if self._model is None:
                self._model = load_metallicity_model(os.fspath(self._checkpoint))
            if self._graph_settings is None:
                from goldilocks_core.ml.model_registry import load_default_qrf_config

                settings = load_default_qrf_config(self._registry_path).feature_settings
                self._graph_settings = (
                    settings.metallicity_graph_radius,
                    settings.metallicity_max_neighbors,
                )
            model = self._model
            atom_init = os.fspath(self._atom_init)
            graph_radius, max_neighbors = self._graph_settings

        character, confidence = classify_metallicity(
            structure,
            model,
            atom_init,
            graph_radius=graph_radius,
            max_neighbors=max_neighbors,
        )
        return character, "model", confidence

    def _resolve_default_artifacts(self) -> bool:
        from goldilocks_core.ml.model_registry import load_default_qrf_config

        config = load_default_qrf_config(self._registry_path)
        asset = config.metallicity_asset
        if asset is None:
            return False
        try:
            installed = self._asset_store.resolve_spec(asset)
        except AssetNotInstalled:
            return False
        self._checkpoint = installed.path(config.metallicity_checkpoint_file)
        self._atom_init = installed.path(config.metallicity_atom_init_file)
        self._graph_settings = (
            config.feature_settings.metallicity_graph_radius,
            config.feature_settings.metallicity_max_neighbors,
        )
        return True

    def reset(self) -> None:
        with self._load_lock:
            self._model = None

    def close(self) -> None:
        with self._load_lock:
            self._model = None
            self._graph_settings = None
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
        metallicity_configuration = (
            metallicity_checkpoint,
            metallicity_atom_init,
            metallicity_model,
        )
        configured = tuple(item is not None for item in metallicity_configuration)
        if any(configured) and not all(configured):
            raise ValueError(
                "metallicity_checkpoint, metallicity_atom_init, and "
                "metallicity_model must be configured together"
            )
        self._registry_path = registry_path
        self._metallicity_checkpoint = metallicity_checkpoint
        self._metallicity_atom_init = metallicity_atom_init
        self._metallicity_model_spec = metallicity_model
        self._uses_default_metallicity_model = not any(configured)
        self._asset_store = asset_store or AssetStore()
        self._pseudo_registry_path = pseudo_registry_path
        self._uses_default_kmesh_model = kmesh_service is None
        self._backend = (
            kmesh_service if kmesh_service is not None else self._build_backend()
        )
        self._metallicity = self._build_metallicity()
        self._closed = False

    def _build_backend(self) -> QrfBackend:
        return QrfBackend(
            registry_path=self._registry_path,
            metallicity_checkpoint=self._metallicity_checkpoint,
            metallicity_atom_init=self._metallicity_atom_init,
            asset_store=self._asset_store,
        )

    def _build_metallicity(self) -> MetallicityModel:
        return MetallicityModel(
            checkpoint=self._metallicity_checkpoint,
            atom_init=self._metallicity_atom_init,
            registry_path=self._registry_path,
            asset_store=self._asset_store,
        )

    @property
    def kmesh_service(self) -> KMeshService:
        return self._backend

    @property
    def uses_default_kmesh_model(self) -> bool:
        return self._uses_default_kmesh_model

    @property
    def metallicity_model_spec(self) -> ModelSpec | None:
        return self._metallicity_model_spec

    @property
    def uses_default_metallicity_model(self) -> bool:
        return self._uses_default_metallicity_model

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
