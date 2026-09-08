from __future__ import annotations

import os
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from typing import Annotated, Protocol, TypedDict, runtime_checkable

from pymatgen.core import Structure

from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.advice.kindex import ml_kmesh_advisor
from goldilocks_core.analysis import StructureAnalysisRecord, heuristic_metallicity
from goldilocks_core.assets.records import AssetSpec
from goldilocks_core.assets.store import AssetNotInstalled, AssetStore
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.generation.files import InputArtifact
from goldilocks_core.kmesh.resolve import KMeshAdvisor, KPointSelection
from goldilocks_core.ml.models import (
    ModelSpec,
    QrfKpointsConfig,
    load_default_qrf_config,
)
from goldilocks_core.serialization import Portable, to_portable
from goldilocks_core.types import ElectronicCharacter, JsonDict, PathLike


class ModelMetadataError(ExpectedFailure, ValueError):
    """A local model lacks the legal metadata required for publication."""

    kind = "invalid_model_metadata"
    category = "local"


class RuntimeAssetIdentity(TypedDict):
    id: str
    version: str
    preparation_fingerprint: str


class RuntimeIdentity(TypedDict):
    core_version: str
    models: list[Annotated[JsonDict, Portable(ModelSpec)]]
    assets: list[RuntimeAssetIdentity]


@dataclass(frozen=True, slots=True)
class RuntimeMaterial:
    artifacts: tuple[InputArtifact, ...]
    identity: RuntimeIdentity
    citations: tuple[str, ...]


@runtime_checkable
class KMeshService(Protocol):
    def __call__(self, structure: Structure) -> JsonDict: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


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

    def materialize_models(
        self,
        analysis: StructureAnalysisRecord,
        k_points: KPointSelection,
        *,
        kmesh_model: ModelSpec | None = None,
    ) -> RuntimeMaterial:
        """Snapshot identity and legal material only for models actually used."""
        materials = self._used_models(analysis, k_points, kmesh_model)
        artifacts: list[InputArtifact] = []
        identities: list[RuntimeAssetIdentity] = []
        citations: list[str] = []
        for material in materials:
            model = material.spec
            if material.asset is None:
                missing = [
                    field
                    for field in ("licence", "licence_text", "citation")
                    if not isinstance(getattr(model, field), str)
                    or not getattr(model, field).strip()
                ]
                if missing:
                    raise ModelMetadataError(
                        f"Model {model.name!r} used for publication must declare "
                        "non-empty licence, licence_text, and citation"
                    )
                citations.append(model.citation)
                artifacts.append(
                    {
                        "path": material.licence_path,
                        "role": "licence",
                        "content": model.licence_text.encode("utf-8"),
                    }
                )
                continue

            citations.append(model.citation)
            installed = self._asset_store.resolve_spec(material.asset)
            identity: RuntimeAssetIdentity = {
                "id": installed.id,
                "version": installed.version,
                "preparation_fingerprint": installed.preparation_fingerprint,
            }
            if identity in identities:
                continue
            licence = next(
                file for file in material.asset.files if file.role == "licence"
            )
            suffix = Path(licence.path).suffix or ".txt"
            licence_name = material.asset.id.replace("/", "_")
            artifacts.append(
                {
                    "path": f"licences/{licence_name}-{material.asset.version}{suffix}",
                    "role": "licence",
                    "content": installed.read_bytes(licence.path),
                }
            )
            identities.append(identity)
        return RuntimeMaterial(
            tuple(artifacts),
            {
                "core_version": version("goldilocks-core"),
                "models": [to_portable(item.spec) for item in materials],
                "assets": identities,
            },
            tuple(citations),
        )

    def _used_models(
        self,
        analysis: StructureAnalysisRecord,
        k_points: KPointSelection,
        kmesh_model: ModelSpec | None,
    ) -> tuple[_ModelMaterial, ...]:
        config = (
            self._backend.loaded_config
            if self._uses_default_kmesh_model and isinstance(self._backend, QrfBackend)
            else None
        )
        materials: list[_ModelMaterial] = []
        if k_points["provenance"].source == "model":
            if kmesh_model is not None:
                materials.append(
                    _ModelMaterial(kmesh_model, None, "licences/custom-kmesh-model.txt")
                )
            elif config is not None:
                materials.append(
                    _ModelMaterial(
                        config.model, config.model_asset, "licences/k-point-model.txt"
                    )
                )
                # QRF uses its own classifier resources for feature extraction.
                materials.append(self._metallicity_material(config))
            else:
                raise ValueError(
                    "KMeshService produced a model result without loaded identity; "
                    "supply a CalculationDraft.kmesh_model with explicit licence and "
                    "citation material"
                )
        if analysis["electronic_character_source"] == "model":
            material = self._metallicity_material(self._metallicity.loaded_config)
            if material not in materials:
                if material.asset is None and any(
                    item.licence_path == material.licence_path for item in materials
                ):
                    material = replace(
                        material, licence_path="licences/analysis-metallicity-model.txt"
                    )
                materials.append(material)
        return tuple(materials)

    def _metallicity_material(self, config: QrfKpointsConfig | None) -> _ModelMaterial:
        if self._metallicity_model_spec is not None:
            return _ModelMaterial(
                self._metallicity_model_spec,
                None,
                "licences/custom-metallicity-model.txt",
            )
        if config is not None:
            return _ModelMaterial(
                config.metallicity_model,
                config.metallicity_asset,
                "licences/metallicity-model.txt",
            )
        raise ValueError(
            "Metallicity classifier produced a model result without loaded identity; "
            "supply Runtime(metallicity_model=ModelSpec(...)) with explicit licence "
            "and citation material"
        )

    def describe_models(self) -> list[dict[str, str | None]]:
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


@dataclass(frozen=True, slots=True)
class _ModelMaterial:
    spec: ModelSpec
    asset: AssetSpec | None
    licence_path: str


class ModelResolution:
    """Request-local model choice and publication over shared runtime services."""

    def __init__(self, runtime: Runtime, kmesh_model: ModelSpec | None) -> None:
        self.kmesh_advisor: KMeshAdvisor = (
            ml_kmesh_advisor(kmesh_model)
            if kmesh_model is not None
            else runtime._backend
        )
        self.metallicity_classifier = runtime.metallicity
        self._runtime = runtime
        self._kmesh_model = kmesh_model

    def materialize(
        self, analysis: StructureAnalysisRecord, k_points: KPointSelection
    ) -> RuntimeMaterial:
        return self._runtime.materialize_models(
            analysis, k_points, kmesh_model=self._kmesh_model
        )
