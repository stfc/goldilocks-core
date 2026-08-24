from __future__ import annotations

import os

from pymatgen.core import Structure

from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.analysis import heuristic_metallicity
from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import (
    ElectronicCharacter,
    KMeshService,
    ModelSpec,
    PathLike,
)


class MetallicityModel:
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
        if self._closed:
            raise RuntimeError("MetallicityModel is closed.")
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
        self._model = None

    def close(self) -> None:
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
        self._registry_path = registry_path
        self._metallicity_checkpoint = metallicity_checkpoint
        self._metallicity_atom_init = metallicity_atom_init
        self._metallicity_model_spec = metallicity_model
        if (metallicity_checkpoint is None) != (metallicity_atom_init is None):
            raise ValueError(
                "metallicity_checkpoint and metallicity_atom_init must be configured "
                "together"
            )
        self._uses_default_metallicity_model = metallicity_checkpoint is None
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
