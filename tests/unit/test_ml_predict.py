"""ml.predict: the registered-model seam (#11, #92, #130).

A model that is not set up raises ``MlModelUnavailable``, the only signal
callers fall back to their next tier on. Not set up means its asset is not
installed or fails verification, or, for is_magnetic, the mMACE backbone is
not configured or the mace packages are not installed. A model that is set
up but fails while loading or predicting fails the caller instead: a model
broken by another request's torch state used to look like a missing one,
and the caller silently answered from its heuristic (#130).

A prediction keeps what the model returned -- its id, target contract,
details and warnings, verbatim -- with the registry's asset and citation, as
the ``Provenance`` of the record it decides (#156).

None of these tests needs real assets. A stub store resolves every asset to
a temporary directory and goldilocks-ml's ``load_model`` (or the mace worker)
is stubbed to return real ``ModelPrediction``s.
``tests/integration/test_mace_isolation.py`` runs the real models.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
from goldilocks_ml.inference import ModelPrediction
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors import magnetic_ordering_ml
from goldilocks_core.advisors.k_sampling import k_sampling
from goldilocks_core.analysis.is_magnetic import IsMagneticLlmInput, is_magnetic
from goldilocks_core.analysis.is_metal import is_metal
from goldilocks_core.assets.records import AssetReference
from goldilocks_core.assets.store import AssetCorrupt, AssetNotInstalled
from goldilocks_core.ml import mace_process, predict as predict_module
from goldilocks_core.ml.models import load_default_qrf_config, load_ml_classifier
from goldilocks_core.ml.predict import (
    MlModelUnavailable,
    model_ready,
    predict,
    predict_k_distance,
)
from goldilocks_core.resolution import ModelEvidence, Provenance, Resolved, Warning

_SILICON = Structure.from_spacegroup(
    "Fd-3m", Lattice.cubic(5.43), ["Si"], [[0.0, 0.0, 0.0]]
)
_IRON = Structure.from_spacegroup(
    "Im-3m", Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]]
)
_MODEL_FAILURE = "mat1 and mat2 must have the same dtype, but got Float and Double"
_IS_METAL_ID = "metallicity.is_metal.cgcnn@crystal_graph.v1"
_IS_MAGNETIC_ID = "magnetism.is_magnetic.mace_mlp@mace_probe_embedding.v1"
_QRF95_ID = "k_points.k_distance.qrf@comp_struct_soap_lattice_metal.v1"
_UNCALIBRATED = (
    f"{_QRF95_ID} records no conformal calibration, so its interval carries no "
    "coverage guarantee. The median is unaffected."
)
_UNVALIDATED = (
    f"{_IS_MAGNETIC_ID} has not been externally validated (MP-ALOE external "
    "validation has not been run.)"
)


def _is_metal_prediction(**details: Any) -> ModelPrediction:
    """What the published CGCNN returned for MC3D Si (mc3d-42058)."""
    return ModelPrediction(
        parameter="metallicity",
        quantity="is_metal",
        value=False,
        target_contract="goldilocks.is_metal.dft_band_gap_zero.v1",
        model_id=_IS_METAL_ID,
        details={
            "score": 0.008642838336527348,
            "threshold": 0.04782969690859318,
            "label": "insulator",
            "min_recall": 0.97,
            **details,
        },
    )


_IS_METAL_PREDICTION = _is_metal_prediction()

_QRF95_PREDICTION = ModelPrediction(
    parameter="k_points",
    quantity="k_distance",
    value=0.21744443476200104,
    target_contract="goldilocks.k_distance.mesh_lower_bound.2pi.v1",
    model_id=_QRF95_ID,
    details={
        "interval": [0.11168761551380157, 0.503409206867218],
        "coverage": None,
        "calibrated": False,
        "units": "1/angstrom",
    },
    warnings=(_UNCALIBRATED,),
)
"""What QRF95 returned for MC3D Si (mc3d-42058)."""

_IS_MAGNETIC_PREDICTION = ModelPrediction(
    parameter="magnetism",
    quantity="is_magnetic",
    value=True,
    target_contract="goldilocks.is_magnetic.dft_max_site_magmom_0p5ub.v1",
    model_id=_IS_MAGNETIC_ID,
    details={"score": 0.3598, "threshold": 0.323869526386261, "label": "magnetic"},
    warnings=(_UNVALIDATED,),
)
"""TiNi (MC3D mc3d-31340) as the issue quotes it (#156)."""

_IN_PROCESS_PREDICTIONS = [
    pytest.param(
        lambda store: predict("is_metal", _SILICON, store=store), id="is_metal"
    ),
    pytest.param(
        lambda store: predict_k_distance(_SILICON, store=store), id="k_distance"
    ),
]
"""The two models that run in this process, each on a given store."""


class _StubStore:
    """Resolves every asset to one directory, as if installed and verified."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_spec(self, spec: Any) -> SimpleNamespace:
        return SimpleNamespace(root=self.root)


class _UnusableStore:
    """Fails every asset the way ``AssetStore`` does for a missing or
    corrupt install."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def resolve_spec(self, spec: Any) -> SimpleNamespace:
        raise self.error


class _Model:
    def __init__(
        self,
        error: Exception | None = None,
        prediction: ModelPrediction = _IS_METAL_PREDICTION,
    ) -> None:
        self.error = error
        self.prediction = prediction

    def predict(self, structure: Structure) -> ModelPrediction:
        if self.error is not None:
            raise self.error
        return self.prediction


@pytest.fixture(autouse=True)
def fresh_model_cache() -> Iterator[None]:
    """Models are cached per installed directory for the life of the
    process; no test may see another test's stub."""
    predict_module._model.cache_clear()
    yield
    predict_module._model.cache_clear()


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, dict[str, Any]]]:
    """Every ``load_model`` call, each returning a model that predicts."""
    calls: list[tuple[Path, dict[str, Any]]] = []

    def fake_load_model(directory: Path, **kwargs: Any) -> _Model:
        calls.append((directory, kwargs))
        return _Model()

    monkeypatch.setattr("goldilocks_ml.inference.load_model", fake_load_model)
    return calls


@pytest.fixture
def failing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``load_model`` returns a model whose prediction raises the dtype
    error a float64 default dtype caused (#130)."""
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda directory, **kwargs: _Model(RuntimeError(_MODEL_FAILURE)),
    )


@pytest.fixture
def backbone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    checkpoint = tmp_path / "backbone.model"
    checkpoint.write_bytes(b"stub")
    monkeypatch.setenv("GOLDILOCKS_MACE_BACKBONE", str(checkpoint))
    return checkpoint


@pytest.fixture
def mace_packages(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """The packages ``find_spec`` reports installed: mace, e3nn and
    sphericart unless a test removes one (CI installs none of them)."""
    installed = {"mace", "e3nn", "sphericart"}
    monkeypatch.setattr(
        magnetic_ordering_ml,
        "find_spec",
        lambda name: ModuleSpec(name, None) if name in installed else None,
    )
    return installed


@pytest.mark.parametrize("run", _IN_PROCESS_PREDICTIONS)
def test_a_model_that_fails_to_run_fails_the_prediction(
    run, tmp_path: Path, failing_model: None
) -> None:
    with pytest.raises(RuntimeError, match=_MODEL_FAILURE):
        run(_StubStore(tmp_path))


@pytest.mark.parametrize("run", _IN_PROCESS_PREDICTIONS)
def test_a_model_loads_once_from_its_installed_directory(
    run, tmp_path: Path, loads: list[tuple[Path, dict[str, Any]]]
) -> None:
    """The artifacts a deposit ships beside its ``model.json`` are read from
    there, never from goldilocks-ml's default directory, which is relative to
    the working directory and can be deleted under a running server."""
    store = _StubStore(tmp_path)

    run(store)
    run(store)

    assert loads == [(tmp_path, {"artifact_directory": tmp_path})]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            AssetNotInstalled(
                AssetReference("models/is-metal-classifier", "1"), Path("/assets")
            ),
            id="not-installed",
        ),
        pytest.param(AssetCorrupt("installed file changed"), id="corrupt"),
    ],
)
def test_a_model_whose_asset_is_unusable_is_unavailable(
    error: Exception, loads: list[tuple[Path, dict[str, Any]]]
) -> None:
    with pytest.raises(
        MlModelUnavailable, match="goldilocks assets install models/is-metal-classifier"
    ):
        predict("is_metal", _SILICON, store=_UnusableStore(error))

    assert loads == []


def test_model_ready_makes_the_checks_a_prediction_makes_first(
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    loads: list[tuple[Path, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``capabilities`` lists the ``ml`` approach from this, so it must agree
    with what a prediction would do, without loading or running a model."""

    def no_worker(model_root: Path, checkpoint: Path, structure: Structure) -> None:
        raise AssertionError("model_ready must not run is_magnetic")

    monkeypatch.setattr(mace_process, "predict_is_magnetic", no_worker)
    monkeypatch.setattr(predict_module, "AssetStore", lambda: _StubStore(tmp_path))
    targets = ("is_metal", "k_distance", "is_magnetic", "k_index")

    assert [model_ready(target) for target in targets] == [True, True, True, False]
    mace_packages.discard("sphericart")
    assert [model_ready(target) for target in targets] == [True, True, False, False]
    monkeypatch.setattr(
        predict_module, "AssetStore", lambda: _UnusableStore(AssetCorrupt("changed"))
    )
    assert [model_ready(target) for target in targets] == [False] * 4
    assert loads == []


def test_is_magnetic_runs_on_the_mace_worker_with_the_installed_model_and_backbone(
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_predict_is_magnetic(
        model_root: Path, checkpoint: Path, structure: Structure
    ) -> ModelPrediction:
        calls.append((model_root, checkpoint, structure))
        return _IS_MAGNETIC_PREDICTION

    monkeypatch.setattr(mace_process, "predict_is_magnetic", fake_predict_is_magnetic)

    prediction = predict("is_magnetic", _IRON, store=_StubStore(tmp_path))

    assert prediction.value is True
    assert prediction.provenance.model.model_id == _IS_MAGNETIC_ID
    assert calls == [(tmp_path, backbone, _IRON)]


def test_is_magnetic_hands_the_worker_an_absolute_backbone_path(
    tmp_path: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker starts in the system temporary directory, so a relative
    ``GOLDILOCKS_MACE_BACKBONE`` reaches it resolved against the caller's
    working directory."""
    (tmp_path / "backbone.model").write_bytes(b"stub")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GOLDILOCKS_MACE_BACKBONE", "backbone.model")
    checkpoints = []

    def fake_predict_is_magnetic(
        model_root: Path, checkpoint: Path, structure: Structure
    ) -> ModelPrediction:
        checkpoints.append(checkpoint)
        return _IS_MAGNETIC_PREDICTION

    monkeypatch.setattr(mace_process, "predict_is_magnetic", fake_predict_is_magnetic)

    predict("is_magnetic", _IRON, store=_StubStore(tmp_path))

    assert checkpoints == [tmp_path / "backbone.model"]


@pytest.mark.parametrize("missing", ["mace", "e3nn", "sphericart"])
def test_is_magnetic_is_unavailable_without_a_mace_package(
    missing: str,
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    loads: list[tuple[Path, dict[str, Any]]],
) -> None:
    mace_packages.discard(missing)

    with pytest.raises(MlModelUnavailable, match=f"^{missing} not installed"):
        predict("is_magnetic", _IRON, store=_StubStore(tmp_path))


def test_is_magnetic_is_unavailable_without_a_configured_backbone(
    tmp_path: Path, mace_packages: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOLDILOCKS_MACE_BACKBONE", raising=False)

    with pytest.raises(MlModelUnavailable, match="GOLDILOCKS_MACE_BACKBONE"):
        predict("is_magnetic", _IRON, store=_StubStore(tmp_path))


def test_is_magnetic_is_unavailable_when_the_configured_backbone_is_missing(
    tmp_path: Path, mace_packages: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDILOCKS_MACE_BACKBONE", str(tmp_path / "missing.model"))

    with pytest.raises(MlModelUnavailable, match="does not exist"):
        predict("is_magnetic", _IRON, store=_StubStore(tmp_path))


@pytest.mark.parametrize(
    "modules",
    [
        pytest.param({"mace": None}, id="no-mace"),
        pytest.param(
            {
                name: ModuleType(name)
                for name in (
                    "mace",
                    "mace.calculators",
                    "mace.calculators.mace",
                    "mace.modules",
                )
            },
            id="mace-before-0.3.17",
        ),
    ],
)
def test_the_mace_worker_reports_a_mace_without_magnetic_models_as_unavailable(
    modules: dict[str, ModuleType | None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mace-torch older than 0.3.17 passes ``find_spec`` but lacks the
    magnetic classes goldilocks-ml imports. The worker reports that, like no
    mace at all, as unavailable, so is_magnetic falls back instead of failing
    every request."""
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    with pytest.raises(MlModelUnavailable, match=r"mace-torch 0\.3\.17"):
        mace_process._predict_is_magnetic(
            tmp_path, tmp_path / "backbone.model", "cpu", _IRON
        )


@pytest.mark.parametrize(("atoms", "replaced"), [(16, False), (17, True)])
def test_the_is_magnetic_worker_is_replaced_once_idle_after_a_large_structure(
    atoms: int, replaced: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#260: the worker keeps much of a large prediction's memory until it
    exits, so a fresh, warmed one takes over once it is idle."""

    class Worker:
        def __init__(self) -> None:
            self.replacements: list[tuple[object, ...]] = []

        def run(self, fn, *args):
            return "prediction"

        def replace_when_idle(self, after_s, warm_up, *args) -> None:
            self.replacements.append((after_s, warm_up, *args))

    worker = Worker()
    monkeypatch.setattr(mace_process, "_IS_MAGNETIC_WORKER", worker)
    monkeypatch.delenv("GOLDILOCKS_MMACE_DEVICE", raising=False)
    hydrogens = Structure(
        Lattice.cubic(20.0), ["H"] * atoms, [[i / atoms, 0, 0] for i in range(atoms)]
    )
    checkpoint = tmp_path / "backbone.model"

    assert (
        mace_process.predict_is_magnetic(tmp_path, checkpoint, hydrogens)
        == "prediction"
    )
    assert worker.replacements == (
        [
            (
                30.0,
                mace_process._predict_is_magnetic,
                tmp_path,
                checkpoint,
                "cpu",
                mace_process._WARM_UP_CELL,
            )
        ]
        if replaced
        else []
    )


def test_the_is_magnetic_worker_and_its_replacement_embed_on_the_configured_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#268: the device is read in this process, and the worker and the
    warmed replacement it schedules both get it."""
    import torch

    from goldilocks_core.advisors import magnetic_ordering_ml

    class Worker:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def run(self, fn, *args):
            self.calls.append(args)
            return "prediction"

        def replace_when_idle(self, after_s, warm_up, *args) -> None:
            self.calls.append(args)

    worker = Worker()
    monkeypatch.setattr(mace_process, "_IS_MAGNETIC_WORKER", worker)
    monkeypatch.setenv("GOLDILOCKS_MMACE_DEVICE", "cuda")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    magnetic_ordering_ml._cuda_or_cpu.cache_clear()
    hydrogens = Structure(
        Lattice.cubic(20.0), ["H"] * 17, [[i / 17, 0, 0] for i in range(17)]
    )

    mace_process.predict_is_magnetic(tmp_path, tmp_path / "backbone.model", hydrogens)
    magnetic_ordering_ml._cuda_or_cpu.cache_clear()

    assert [call[2] for call in worker.calls] == ["cuda", "cuda"]


def test_the_is_magnetic_model_loads_on_the_device_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = []
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda directory, **kwargs: loads.append((directory, kwargs)),
    )
    mace_process._is_magnetic_model.cache_clear()

    mace_process._is_magnetic_model(tmp_path, tmp_path / "backbone.model", "cuda")
    mace_process._is_magnetic_model.cache_clear()

    assert loads == [
        (
            tmp_path,
            {
                "artifacts": {"mace_backbone": tmp_path / "backbone.model"},
                "artifact_directory": tmp_path,
                "device": "cuda",
            },
        )
    ]


def test_is_magnetic_falls_back_when_the_worker_cannot_import_mace(
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(model_root: Path, checkpoint: Path, structure: Structure) -> None:
        raise MlModelUnavailable("is_magnetic needs mace-torch 0.3.17 or later")

    monkeypatch.setattr(predict_module, "AssetStore", lambda: _StubStore(tmp_path))
    monkeypatch.setattr(mace_process, "predict_is_magnetic", unavailable)

    assert is_magnetic(_IRON).source == "heuristic"


_ABOVE_THE_LIMIT = (
    "2 atoms is above this server's 1-atom limit for mMACE (GOLDILOCKS_MMACE_MAX_ATOMS)"
)


def _set_up_with_a_one_atom_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_magnetic's model is set up and mMACE may run on one atom; any
    worker call fails the test."""

    def no_worker(model_root: Path, checkpoint: Path, structure: Structure) -> None:
        raise AssertionError("no worker call above the atom limit")

    monkeypatch.setattr(predict_module, "AssetStore", lambda: _StubStore(tmp_path))
    monkeypatch.setattr(mace_process, "predict_is_magnetic", no_worker)
    monkeypatch.setenv("GOLDILOCKS_MMACE_MAX_ATOMS", "1")


@pytest.mark.parametrize(
    ("llm", "source", "decider"),
    [
        (None, "heuristic", "the local-moment heuristic"),
        (IsMagneticLlmInput(is_magnetic="non_magnetic"), "llm", "the LLM"),
    ],
    ids=["heuristic", "llm"],
)
def test_is_magnetic_above_the_mmace_atom_limit_says_why_without_a_worker_call(
    llm: IsMagneticLlmInput | None,
    source: str,
    decider: str,
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#259: the classifier's memory grows with the atom count, so a
    structure above the limit gets the next tier's answer -- and the record
    says why, unlike the quiet fall-back of a model that is not set up."""
    _set_up_with_a_one_atom_limit(tmp_path, monkeypatch)

    state = is_magnetic(_IRON, llm=llm)

    assert state.source == source
    assert state.provenance.source_note == (
        f"The mMACE classifier was not run: {_ABOVE_THE_LIMIT}, so {decider} decided."
    )


def test_an_undecidable_is_magnetic_above_the_mmace_atom_limit_says_why_too(
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US: the heuristic cannot decide (``test_is_magnetic.py``), so the
    reason the record is unavailable names the skipped classifier too."""
    _set_up_with_a_one_atom_limit(tmp_path, monkeypatch)
    uranium_sulfide = Structure(
        Lattice.cubic(4.0), ["U", "S"], [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]
    )

    state = is_magnetic(uranium_sulfide)

    assert state.status == "unavailable"
    assert state.reason.startswith("no oxidation-state guess")
    assert state.reason.endswith(
        f"(the mMACE classifier was not run: {_ABOVE_THE_LIMIT})"
    )


def test_is_magnetic_at_the_mmace_atom_limit_runs_the_classifier(
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(predict_module, "AssetStore", lambda: _StubStore(tmp_path))
    monkeypatch.setattr(
        mace_process,
        "predict_is_magnetic",
        lambda root, checkpoint, cell: _IS_MAGNETIC_PREDICTION,
    )
    monkeypatch.setenv("GOLDILOCKS_MMACE_MAX_ATOMS", "2")

    state = is_magnetic(_IRON)

    assert state.source == "ml"
    assert state.provenance.source_note is None


@pytest.mark.parametrize(
    "decide",
    [
        pytest.param(is_metal, id="is_metal"),
        pytest.param(
            lambda structure: k_sampling(
                Resolved("metal", Provenance(source="human")), structure
            ),
            id="k_sampling",
        ),
        pytest.param(is_magnetic, id="is_magnetic"),
    ],
)
def test_a_failing_model_fails_its_caller_instead_of_a_heuristic_answer(
    decide,
    tmp_path: Path,
    failing_model: None,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_worker(
        model_root: Path, checkpoint: Path, structure: Structure
    ) -> None:
        raise RuntimeError(_MODEL_FAILURE)

    monkeypatch.setattr(predict_module, "AssetStore", lambda: _StubStore(tmp_path))
    monkeypatch.setattr(mace_process, "predict_is_magnetic", failing_worker)

    with pytest.raises(RuntimeError, match=_MODEL_FAILURE):
        decide(_IRON)


def _model_returning(
    prediction: ModelPrediction, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda directory, **kwargs: _Model(prediction=prediction),
    )
    monkeypatch.setattr(
        mace_process, "predict_is_magnetic", lambda root, checkpoint, cell: prediction
    )


@pytest.mark.parametrize(
    ("target", "returned", "asset", "citation", "warning"),
    [
        pytest.param(
            "is_metal",
            _IS_METAL_PREDICTION,
            "models/is-metal-classifier@1",
            load_ml_classifier("is_metal").model.citation,
            None,
            id="is_metal",
        ),
        pytest.param(
            "k_distance",
            _QRF95_PREDICTION,
            "models/qrf-kpoints@QRF95",
            load_default_qrf_config().model.citation,
            Warning(
                code="k_sampling.model_warning",
                level="warning",
                category="k_sampling",
                message=_UNCALIBRATED,
            ),
            id="k_distance",
        ),
        pytest.param(
            "is_magnetic",
            _IS_MAGNETIC_PREDICTION,
            "models/is-magnetic-classifier@1",
            load_ml_classifier("is_magnetic").model.citation,
            Warning(
                code="is_magnetic.model_warning",
                level="warning",
                category="is_magnetic",
                message=_UNVALIDATED,
            ),
            id="is_magnetic",
        ),
    ],
)
def test_a_prediction_keeps_what_the_model_returned_with_its_registry_entry(
    target: str,
    returned: ModelPrediction,
    asset: str,
    citation: str,
    warning: Warning | None,
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#156: the seam kept only ``prediction.value``. A record decided by a
    model now names it (goldilocks-ml's id and the registry asset it was
    loaded from), keeps its target contract, details and warnings as
    returned, and cites the registry's citation for it."""
    _model_returning(returned, monkeypatch)
    store = _StubStore(tmp_path)

    prediction = (
        predict_k_distance(_SILICON, store=store)
        if target == "k_distance"
        else predict(target, _SILICON, store=store)
    )

    assert prediction.value == returned.value
    assert prediction.provenance == Provenance(
        source="ml",
        model=ModelEvidence(
            model_id=returned.model_id,
            asset=asset,
            target_contract=returned.target_contract,
            value=returned.value,
            details=dict(returned.details),
            warnings=() if warning is None else (warning,),
        ),
        citations=(citation,),
    )


def test_is_magnetic_cites_its_own_classifier_not_the_k_point_paper() -> None:
    """#156: registry.toml's is_magnetic entry cited the QRF95 k-point paper,
    which nobody noticed because nothing read the field."""
    k_point_paper = load_default_qrf_config().model.citation
    is_magnetic_citation = load_ml_classifier("is_magnetic").model.citation

    assert is_magnetic_citation != k_point_paper
    assert "sgk1t-48m42" in is_magnetic_citation
    assert load_ml_classifier("is_metal").model.citation == k_point_paper


@pytest.mark.parametrize(
    ("details", "problem"),
    [
        pytest.param({"score": float("nan")}, "nan", id="non-finite"),
        pytest.param({"score": np.float32(0.0086)}, "float32", id="numpy-scalar"),
    ],
)
def test_details_without_a_strict_json_form_fail_the_prediction(
    details: dict[str, Any],
    problem: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Details are published verbatim in strict JSON, so a model returning
    a value JSON cannot hold verbatim fails the request, naming the model,
    rather than writing an ``NaN`` or a changed number."""
    _model_returning(_is_metal_prediction(**details), monkeypatch)

    with pytest.raises(ValueError, match=f"{_IS_METAL_ID}.*{problem}"):
        predict("is_metal", _SILICON, store=_StubStore(tmp_path))


def _k_sampling_of(structure: Structure):
    return k_sampling(Resolved("non_metal", Provenance(source="human")), structure)


@pytest.mark.parametrize(
    ("decide", "target", "record_value", "field_sources"),
    [
        pytest.param(is_metal, "is_metal", "non_metal", None, id="is_metal"),
        pytest.param(is_magnetic, "is_magnetic", "magnetic", None, id="is_magnetic"),
        pytest.param(
            _k_sampling_of,
            "k_distance",
            None,
            {"k_distance": "ml", "shift": "heuristic"},
            id="k_sampling",
        ),
    ],
)
def test_a_record_decided_by_a_model_carries_its_prediction_s_provenance(
    decide,
    target: str,
    record_value: str | None,
    field_sources: dict[str, str] | None,
    tmp_path: Path,
    backbone: Path,
    mace_packages: set[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ML tiers of is_metal, is_magnetic and k_sampling resolve with the
    prediction's own ``Provenance``, not a bare ``source="ml"``; k_sampling's
    also names the setting the model decided (#173)."""
    monkeypatch.setattr(predict_module, "AssetStore", lambda: _PerAssetStore(tmp_path))
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda directory, **kwargs: _Model(
            prediction=_QRF95_PREDICTION
            if directory.name == "qrf-kpoints"
            else _IS_METAL_PREDICTION
        ),
    )
    monkeypatch.setattr(
        mace_process,
        "predict_is_magnetic",
        lambda root, checkpoint, cell: _IS_MAGNETIC_PREDICTION,
    )
    prediction = (
        predict_k_distance(_SILICON)
        if target == "k_distance"
        else predict(target, _SILICON)
    )

    state = decide(_SILICON)

    assert state.provenance == prediction.provenance.model_copy(
        update={"field_sources": field_sources}
    )
    if record_value is not None:
        assert state.value == record_value
    else:
        assert state.value.k_distance == _QRF95_PREDICTION.value


class _PerAssetStore:
    """Resolves each asset to its own directory, so each model loads from a
    directory of its own."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_spec(self, spec: Any) -> SimpleNamespace:
        return SimpleNamespace(root=self.root / spec.id)
