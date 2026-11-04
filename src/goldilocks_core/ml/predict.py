"""predict: run a registered, installed ML model on one structure (#11, #92).

The one place ``analysis/is_metal.py``, ``analysis/is_magnetic.py`` and
``advisors/k_sampling.py`` reach a model, never ``goldilocks_ml`` directly.
:class:`MlModelUnavailable` means the model is not set up, and it is the only
failure those callers fall back to their next tier on. Anything raised while
loading or running a model that is set up propagates and fails the caller's
request: a model broken by another request's torch state used to pass for a
missing one, and the request silently got a heuristic answer (#130).

is_metal (CGCNN) and k_distance (QRF95, described by ``QrfKpointsConfig``
rather than ``ml.models.ML_CLASSIFIER_ROLES``) are loaded once per installed
asset directory and run in this process. is_magnetic embeds the structure
with mMACE, which changes process-wide torch state, so it runs on a worker
process (``ml/mace_process.py``) and this process never imports mace.

``goldilocks_ml.inference.load_model`` gets is_magnetic's mMACE backbone
passed as ``artifacts={"mace_backbone": path}``, from
``advisors/magnetic_ordering_ml.checkpoint_path``, the checkpoint ordering
ranking also uses: ``GOLDILOCKS_MACE_BACKBONE`` if set, else the backbone
installed with is_magnetic's asset (#244).

A prediction is an :class:`MlPrediction`: the model's value and the
``Provenance`` of the record it decides, which names the model (its
goldilocks-ml id and the registry asset it was loaded from), keeps its target
contract, details and warnings as returned, and carries the registry's
citation for it (#156). Callers used to keep only the value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from goldilocks_core.assets.store import AssetCorrupt, AssetNotInstalled, AssetStore
from goldilocks_core.ml.models import (
    ML_CLASSIFIER_ROLES,
    ModelSpec,
    load_default_qrf_config,
    load_ml_classifier,
)
from goldilocks_core.resolution import ModelEvidence, Provenance, Warning

if TYPE_CHECKING:
    from pathlib import Path

    from pymatgen.core import Structure

    from goldilocks_core.assets.records import AssetSpec

_RECORDS = {
    "is_metal": "is_metal",
    "is_magnetic": "is_magnetic",
    "k_distance": "k_sampling",
}
"""The record each model target decides."""

_MODEL_WARNINGS = {
    record: Warning(
        code=f"{record}.model_warning",
        level="warning",
        category=record,
        message=(
            f"The model that decided {record} returned a caveat with its "
            "prediction (for example, that it has not been externally "
            "validated); the model's own text is the message."
        ),
    )
    for record in _RECORDS.values()
}
"""Catalogue entry per record; each warning a model returns becomes its
record's entry with the model's text as the message."""

WARNING_CATALOGUE = tuple(_MODEL_WARNINGS.values())
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates it with the advisors'."""


@dataclass(frozen=True, slots=True)
class MlPrediction:
    """One registered model's answer for one structure."""

    value: bool | float
    """The model's value: a classifier's verdict, QRF95's k-distance in
    1/angstrom."""
    provenance: Provenance
    """``source="ml"``, the model's :class:`ModelEvidence` and its registry
    citation: what a record resolved from ``value`` carries."""


class MlModelUnavailable(Exception):
    """A registered model is not set up: its asset is not installed or fails
    verification, or (is_magnetic only) no mMACE backbone is available or
    the mace stack is not installed.

    Callers fall back to their next tier on this and on nothing else; a model
    that is set up but fails to load or predict raises its own error."""


def predict(
    role: str, structure: Structure, *, store: AssetStore | None = None
) -> MlPrediction:
    """The registered ``role`` model's prediction for ``structure``
    (``is_metal`` or ``is_magnetic``).

    Raises :class:`MlModelUnavailable` if the model is not set up, and
    ``ValueError`` if what it returns has no strict JSON form; whatever
    loading or running it raises propagates."""
    return _predict(role, structure, store or AssetStore())


def predict_k_distance(
    structure: Structure, *, store: AssetStore | None = None
) -> MlPrediction:
    """QRF95's prediction (a raw k-distance, 1/angstrom) for ``structure``,
    with the same contract as :func:`predict`."""
    return _predict("k_distance", structure, store or AssetStore())


def _predict(target: str, structure: Structure, store: AssetStore) -> MlPrediction:
    spec, asset = _registration(target)
    root = _installed_root(target, asset, store)
    if target != "is_magnetic":
        return _ml_prediction(target, spec, asset, _model(root).predict(structure))
    checkpoint = _mmace_checkpoint()
    from goldilocks_core.ml.mace_process import predict_is_magnetic

    returned = predict_is_magnetic(root, checkpoint, structure)
    return _ml_prediction(target, spec, asset, returned)


def _ml_prediction(
    target: str, spec: ModelSpec, asset: AssetSpec, returned: Any
) -> MlPrediction:
    """The :class:`MlPrediction` of goldilocks-ml's ``ModelPrediction``
    ``returned``, from the ``target`` model registered as ``spec``/``asset``."""
    template = _MODEL_WARNINGS[_RECORDS[target]]
    evidence = ModelEvidence(
        model_id=returned.model_id,
        asset=f"{asset.id}@{asset.version}",
        target_contract=returned.target_contract,
        value=_verbatim(returned.model_id, "a value", returned.value),
        details=_verbatim(returned.model_id, "details", dict(returned.details or {})),
        warnings=tuple(
            template.model_copy(update={"message": text}) for text in returned.warnings
        ),
    )
    citations = (spec.citation,) if spec.citation else ()
    return MlPrediction(
        value=returned.value,
        provenance=Provenance(source="ml", model=evidence, citations=citations),
    )


def _verbatim(model_id: str, what: str, value: Any) -> Any:
    """``value`` after a strict JSON round trip, the form records publish it
    in; ``ValueError`` naming the model if it has none (a non-finite or
    numpy number), rather than a published ``NaN`` or a changed number."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"model {model_id} returned {what} with no strict JSON form: {error}"
        ) from error


def model_ready(target: str) -> bool:
    """Whether the model registered for ``target`` (``is_metal``,
    ``is_magnetic`` or ``k_distance``) passes the checks :func:`predict` and
    :func:`predict_k_distance` make before running it; ``False`` for any
    other target. Loads and runs nothing."""
    if target not in (*ML_CLASSIFIER_ROLES, "k_distance"):
        return False
    try:
        _installed_root(target, _registration(target)[1], AssetStore())
        if target == "is_magnetic":
            _mmace_checkpoint()
    except MlModelUnavailable:
        return False
    return True


def _registration(target: str) -> tuple[ModelSpec, AssetSpec | None]:
    """``target``'s registered model and the asset it is installed as."""
    if target == "k_distance":
        config = load_default_qrf_config()
        return config.model, config.model_asset
    classifier = load_ml_classifier(target)
    return classifier.model, classifier.asset


def _installed_root(target: str, asset: AssetSpec | None, store: AssetStore) -> Path:
    """The verified installed directory of ``target``'s registered model
    ``asset``."""
    if asset is None:
        raise MlModelUnavailable(f"no {target} model asset is registered")
    try:
        return store.resolve_spec(asset).root
    except (AssetNotInstalled, AssetCorrupt) as error:
        raise MlModelUnavailable(
            f"{target} model asset {asset.id}@{asset.version} is not "
            f"usable: run 'goldilocks assets install {asset.id}'"
        ) from error


def _mmace_checkpoint() -> Path:
    """is_magnetic's mMACE backbone checkpoint, once it is configured and
    mace, e3nn and sphericart are installed."""
    from goldilocks_core.advisors.magnetic_ordering_ml import (
        MagneticOrderingMlUnavailable,
        checkpoint_path,
        require_mace_packages,
    )

    try:
        checkpoint = checkpoint_path()
        require_mace_packages()
    except MagneticOrderingMlUnavailable as error:
        raise MlModelUnavailable(str(error)) from error
    return checkpoint


@cache
def _model(root: Path) -> Any:
    """The model installed at ``root``, loaded on first use and kept for the
    life of the process.

    Its dependencies are read from ``root``, where each deposit ships them
    beside its ``model.json``. goldilocks-ml's default artifact directory is
    relative to the working directory, which a running server cannot rely
    on (#136)."""
    from goldilocks_ml.inference import load_model

    return load_model(root, artifact_directory=root)
