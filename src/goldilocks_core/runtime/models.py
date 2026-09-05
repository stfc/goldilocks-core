from __future__ import annotations

from typing import TYPE_CHECKING

from pymatgen.core import Structure

from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import (
    PREDICTION_RESOLVERS,
    ElectronicCharacter,
    KMeshService,
    ModelSpec,
    PathLike,
    StructureModel,
)

if TYPE_CHECKING:
    from goldilocks_ml.inference import ModelPrediction


def _resolve_metallicity_prediction(
    structure: Structure, prediction: ModelPrediction
) -> tuple[ElectronicCharacter, float | None]:
    """Turn goldilocks-ml's is_metal prediction into an electronic character.

    The prediction already carries the threshold decision -- ``value`` is the
    label, not a raw score -- so there is nothing left for Core to interpret
    beyond the boolean itself. ``details["score"]`` travels through as
    provenance, per the seam's rule that a resolver records details but never
    branches on them.
    """
    del structure
    character: ElectronicCharacter = "metal" if prediction.value else "insulator"
    confidence = prediction.details.get("score") if prediction.details else None
    return character, confidence


PREDICTION_RESOLVERS["metallicity"] = _resolve_metallicity_prediction


class MetallicityModel:
    """Answers is-this-a-metal directly, via goldilocks-ml.

    ``model_dir`` overrides where the model record lives; left unset, it is
    resolved from the runtime asset store on first use, same as the QRF
    k-distance backend resolves its own assets. An asset that is not
    installed raises ``AssetNotInstalled`` -- same as QRF -- rather than
    silently guessing from a heuristic: a model that is expected to run and
    does not is a configuration bug, worth failing loudly over.
    """

    __slots__ = ("_model_dir", "_registry_path", "_asset_store", "_model", "_closed")

    def __init__(
        self,
        *,
        model_dir: PathLike | None,
        registry_path: PathLike | None,
        asset_store: AssetStore,
    ) -> None:
        self._model_dir = model_dir
        self._registry_path = registry_path
        self._asset_store = asset_store
        self._model: StructureModel | None = None
        self._closed = False

    def __call__(
        self, structure: Structure
    ) -> tuple[ElectronicCharacter, str, float | None]:
        if self._closed:
            raise RuntimeError("MetallicityModel is closed.")

        from goldilocks_ml.inference import load_model

        if self._model is None:
            self._model = load_model(self._resolve_model_dir())

        prediction = self._model.predict(structure)
        resolver = PREDICTION_RESOLVERS[prediction.parameter]
        character, confidence = resolver(structure, prediction)
        return character, "model", confidence

    def _resolve_model_dir(self) -> PathLike:
        if self._model_dir is not None:
            return self._model_dir

        from goldilocks_core.ml.model_registry import (
            load_default_electronic_character_config,
        )

        config = load_default_electronic_character_config(self._registry_path)
        installed = self._asset_store.resolve(config.asset.id, config.asset.version)
        return installed.root

    def reset(self) -> None:
        self._model = None

    def close(self) -> None:
        self._model = None
        self._closed = True


class Runtime:
    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        # Feeds the QRF k-distance backend's internal metallicity feature
        # block (ml/qrf/metallicity.py); unrelated to metallicity_model_dir.
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
        # A directory holding a goldilocks-ml model record (model.json plus
        # its estimator) that answers the electronic-character question
        # directly. None resolves the default asset from the asset store,
        # raising AssetNotInstalled if it is not installed.
        metallicity_model_dir: PathLike | None = None,
        kmesh_service: KMeshService | None = None,
        asset_store: AssetStore | None = None,
        pseudo_registry_path: PathLike | None = None,
    ) -> None:
        self._registry_path = registry_path
        self._metallicity_checkpoint = metallicity_checkpoint
        self._metallicity_atom_init = metallicity_atom_init
        self._metallicity_model_dir = metallicity_model_dir
        self._asset_store = asset_store or AssetStore()
        self._pseudo_registry_path = pseudo_registry_path
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
            model_dir=self._metallicity_model_dir,
            registry_path=self._registry_path,
            asset_store=self._asset_store,
        )

    @property
    def kmesh_service(self) -> KMeshService:
        return self._backend

    @property
    def metallicity(self) -> MetallicityModel:
        return self._metallicity

    @property
    def asset_store(self) -> AssetStore:
        return self._asset_store

    @property
    def pseudo_registry_path(self) -> PathLike | None:
        return self._pseudo_registry_path

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
