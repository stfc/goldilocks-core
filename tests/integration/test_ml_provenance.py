"""#156: a record an ML model decided names the model and keeps what it
returned, and the bundle cites every model that shaped the input.

Every record used to publish six keys, so ``is_metal``, ``is_magnetic`` and
``k_sampling`` said only ``source: "ml"``: no model id, no score or
threshold, no QRF95 interval, none of the model's warnings, and
``CITATIONS.md`` listed only the pseudopotential paper.

The CI-runnable tests install the offline SSSP fixture table and stub
goldilocks-ml's ``load_model`` (and the mMACE worker) with the real
``ModelPrediction``s the published models return for MC3D Si (mc3d-42058),
the is_magnetic one carrying its "not externally validated" warning as the
TiNi run did. ``test_installed_models_are_named_in_the_records`` runs the
installed is_metal and QRF95 models and skips without them.
"""

from __future__ import annotations

from importlib.machinery import ModuleSpec
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from goldilocks_ml.inference import ModelPrediction
from support import mc3d_42058_silicon, sssp_fixture_table_spec, strict_json

from goldilocks_core.advisors import magnetic_ordering_ml
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import bundle_files
from goldilocks_core.ml import mace_process, predict as predict_module
from goldilocks_core.ml.models import load_default_qrf_config, load_ml_classifier
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument

_IS_METAL_ID = "metallicity.is_metal.cgcnn@crystal_graph.v1"
_IS_MAGNETIC_ID = "magnetism.is_magnetic.mace_mlp@mace_probe_embedding.v1"
_QRF95_ID = "k_points.k_distance.qrf@comp_struct_soap_lattice_metal.v1"
_UNCALIBRATED = (
    f"{_QRF95_ID} records no conformal calibration, so its interval carries no "
    "coverage guarantee. The median is unaffected."
)
_UNVALIDATED = (
    f"{_IS_MAGNETIC_ID} has not been externally validated (MP-ALOE external "
    "validation has not been run. The metrics in training.test_metrics are an "
    "in-distribution MatPES PBE test split only. Do not treat this release as "
    "is_default until MP-ALOE validation is recorded here.)"
)
_IS_METAL_DETAILS = {
    "score": 0.008642838336527348,
    "threshold": 0.04782969690859318,
    "label": "insulator",
    "score_is": "uncalibrated positive-class softmax",
    "threshold_selected_on": "validation",
    "threshold_metric": "mcc",
    "min_recall": 0.97,
}
_QRF95_DETAILS = {
    "interval": [0.11168761551380157, 0.503409206867218],
    "coverage": None,
    "calibrated": False,
    "units": "1/angstrom",
}
_IS_MAGNETIC_DETAILS = {
    "score": 0.0213,
    "threshold": 0.323869526386261,
    "label": "non_magnetic",
    "score_is": "uncalibrated positive-class sigmoid",
    "threshold_selected_on": "validation",
}
_PREDICTIONS = {
    "is-metal-classifier": ModelPrediction(
        parameter="metallicity",
        quantity="is_metal",
        value=False,
        target_contract="goldilocks.is_metal.dft_band_gap_zero.v1",
        model_id=_IS_METAL_ID,
        details=_IS_METAL_DETAILS,
    ),
    "qrf-kpoints": ModelPrediction(
        parameter="k_points",
        quantity="k_distance",
        value=0.21744443476200104,
        target_contract="goldilocks.k_distance.mesh_lower_bound.2pi.v1",
        model_id=_QRF95_ID,
        details=_QRF95_DETAILS,
        warnings=(_UNCALIBRATED,),
    ),
}
_IS_MAGNETIC_PREDICTION = ModelPrediction(
    parameter="magnetism",
    quantity="is_magnetic",
    value=False,
    target_contract="goldilocks.is_magnetic.dft_max_site_magmom_0p5ub.v1",
    model_id=_IS_MAGNETIC_ID,
    details=_IS_MAGNETIC_DETAILS,
    warnings=(_UNVALIDATED,),
)
_K_POINT_PAPER = load_default_qrf_config().model.citation
_IS_MAGNETIC_CITATION = load_ml_classifier("is_magnetic").model.citation
_TABLE_CITATION = "Synthetic SSSP fixture, cite me."


class _Model:
    def __init__(self, prediction: ModelPrediction) -> None:
        self.prediction = prediction

    def predict(self, structure: Any) -> ModelPrediction:
        return self.prediction


class _ModelStore:
    """Resolves each model asset to a directory named after it, as if
    installed and verified."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_spec(self, spec: Any) -> SimpleNamespace:
        return SimpleNamespace(root=self.root / spec.id)


@pytest.fixture
def fixture_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The offline Si table, installed in the asset root and the only table
    the registry declares; its sources stay outside that root."""
    spec, table = sssp_fixture_table_spec(tmp_path / "sources")
    root = tmp_path / "assets"
    AssetStore(root).install(spec, sssp_preparer(table))
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(root))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {table.id: table},
    )


@pytest.fixture
def stub_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every registered model set up, each returning its real prediction for
    MC3D Si; the in-process model cache starts and ends empty."""
    backbone = tmp_path / "backbone.model"
    backbone.write_bytes(b"stub")
    monkeypatch.setenv("GOLDILOCKS_MACE_BACKBONE", str(backbone))
    monkeypatch.setattr(
        magnetic_ordering_ml, "find_spec", lambda name: ModuleSpec(name, None)
    )
    monkeypatch.setattr(
        predict_module, "AssetStore", lambda: _ModelStore(tmp_path / "models")
    )
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda directory, **kwargs: _Model(_PREDICTIONS[directory.name]),
    )
    monkeypatch.setattr(
        mace_process,
        "predict_is_magnetic",
        lambda root, checkpoint, structure: _IS_MAGNETIC_PREDICTION,
    )
    predict_module._model.cache_clear()
    yield
    predict_module._model.cache_clear()


def _published() -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    """``/explain``, the ``/run`` summary and the bundle files for MC3D Si."""
    document = ComputeRequestDocument(
        structure_content=mc3d_42058_silicon().to(fmt="cif"), hpc="scarf"
    )
    explained = _handlers.explain(document)
    summary, bundle_input = _handlers.run(document)
    files = {file["path"]: file["content"] for file in bundle_files(bundle_input)}
    return explained, summary, files


def _model_warning(record: str, message: str) -> dict[str, str]:
    return {
        "code": f"{record}.model_warning",
        "level": "warning",
        "category": record,
        "message": message,
    }


@pytest.mark.usefixtures("fixture_table", "stub_models")
def test_each_ml_record_names_its_model_and_keeps_what_it_returned() -> None:
    explained, summary, files = _published()
    manifest = strict_json(files["goldilocks.json"])

    expected = {
        "is_metal": (
            "non_metal",
            {
                "model_id": _IS_METAL_ID,
                "asset": "models/is-metal-classifier@1",
                "target_contract": "goldilocks.is_metal.dft_band_gap_zero.v1",
                "value": False,
                "details": _IS_METAL_DETAILS,
                "warnings": [],
            },
            [_K_POINT_PAPER],
        ),
        "is_magnetic": (
            "non_magnetic",
            {
                "model_id": _IS_MAGNETIC_ID,
                "asset": "models/is-magnetic-classifier@1",
                "target_contract": (
                    "goldilocks.is_magnetic.dft_max_site_magmom_0p5ub.v1"
                ),
                "value": False,
                "details": _IS_MAGNETIC_DETAILS,
                "warnings": [_model_warning("is_magnetic", _UNVALIDATED)],
            },
            [_IS_MAGNETIC_CITATION],
        ),
        "k_sampling": (
            None,
            {
                "model_id": _QRF95_ID,
                "asset": "models/qrf-kpoints@QRF95",
                "target_contract": "goldilocks.k_distance.mesh_lower_bound.2pi.v1",
                "value": 0.21744443476200104,
                "details": _QRF95_DETAILS,
                "warnings": [_model_warning("k_sampling", _UNCALIBRATED)],
            },
            [_K_POINT_PAPER],
        ),
    }
    for name, (value, model, citations) in expected.items():
        record = manifest["records"][name]
        assert (record["source"], record["model"], record["citations"]) == (
            "ml",
            model,
            citations,
        ), name
        if value is not None:
            assert record["value"] == value
        assert explained["records"][name] == record
        assert summary["records"][name] == record
    assert manifest["records"]["k_sampling"]["value"]["k_distance"] == (
        0.21744443476200104
    )


@pytest.mark.usefixtures("fixture_table", "stub_models")
def test_model_warnings_reach_every_warnings_list_with_their_record() -> None:
    explained, summary, files = _published()
    manifest = strict_json(files["goldilocks.json"])

    expected = [
        {**_model_warning("is_magnetic", _UNVALIDATED), "record": "is_magnetic"},
        {**_model_warning("k_sampling", _UNCALIBRATED), "record": "k_sampling"},
    ]
    for warnings in (explained["warnings"], summary["warnings"], manifest["warnings"]):
        assert [w for w in warnings if w["code"].endswith(".model_warning")] == (
            expected
        )


@pytest.mark.usefixtures("fixture_table", "stub_models")
def test_the_bundle_cites_every_model_and_the_table() -> None:
    _explained, _summary, files = _published()
    manifest = strict_json(files["goldilocks.json"])

    cited = sorted({_K_POINT_PAPER, _IS_MAGNETIC_CITATION, _TABLE_CITATION})
    assert manifest["citations"] == cited
    entries = "".join(f"- {citation}\n" for citation in cited)
    assert f"results.\n\n{entries}\n## Licences\n" in (
        files["CITATIONS.md"].decode("utf-8")
    )
    assert manifest["records"]["pseudo_table"]["citations"] == [_TABLE_CITATION]


@pytest.mark.usefixtures("real_assets")
def test_installed_models_are_named_in_the_records() -> None:
    """Local only: the installed is_metal CGCNN and QRF95 name themselves in
    the records, and QRF95's own interval and calibration caveat are kept."""
    predict_module._model.cache_clear()
    document = ComputeRequestDocument(
        structure_content=mc3d_42058_silicon().to(fmt="cif"), hpc="scarf"
    )

    explained = _handlers.explain(document)

    records = explained["records"]
    is_metal_model = records["is_metal"]["model"]
    assert (is_metal_model["model_id"], is_metal_model["asset"]) == (
        _IS_METAL_ID,
        "models/is-metal-classifier@1",
    )
    assert set(is_metal_model["details"]) >= {"score", "threshold"}
    k_model = records["k_sampling"]["model"]
    assert (k_model["model_id"], k_model["asset"]) == (
        _QRF95_ID,
        "models/qrf-kpoints@QRF95",
    )
    low, high = k_model["details"]["interval"]
    assert low <= k_model["value"] <= high
    assert records["k_sampling"]["value"]["k_distance"] == k_model["value"]
    assert {
        "code": "k_sampling.model_warning",
        "level": "warning",
        "category": "k_sampling",
        "message": _UNCALIBRATED,
        "record": "k_sampling",
    } in explained["warnings"]
