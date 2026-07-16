import gc
import hashlib
import json
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from time import sleep

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import CoreJobRequest, CoreRuntime, Pipeline, run_core_job
from goldilocks_core.advisors.kdistance_advisor import (
    default_kmesh_advisor,
    kdistance_to_selection,
    predict_kdistance_quantiles,
    qrf_kdistance_advisor,
)
from goldilocks_core.contracts import (
    CalculationHints,
    KPointAdvice,
    Provenance,
    RuntimeResource,
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh
from goldilocks_core.ml.model_registry import (
    MODEL_REGISTRY_ENV,
    RuntimeRequirement,
    load_default_qrf_config,
)


class FakeQRF:
    """Minimal QRF stub returning fixed (lower, median, upper) quantiles."""

    def __init__(
        self,
        lower,
        median,
        upper,
        *,
        q=(0.05, 0.5, 0.95),
    ):
        self.q = list(q)
        self._quantiles = np.array([[lower], [median], [upper]])

    def predict(self, X):
        return self._quantiles


def make_features() -> StructureFeatureVector:
    return StructureFeatureVector(
        values=np.zeros(4), feature_names=["a", "b", "c", "d"]
    )


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_config():
    return load_default_qrf_config()


def _make_advice() -> KPointAdvice:
    return KPointAdvice(
        spacing=0.2,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="baseline"),
    )


def _patch_models(monkeypatch, qrf: FakeQRF) -> None:
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", lambda spec: qrf)
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model", lambda path: object()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )


def _assert_qrf_failure_context(selection, config, stage, error) -> dict:
    """Assert serialized fallback details retain a parsed QRF contract."""
    inference = selection.provenance.details["qrf_inference"]
    assert inference["config_digest"] == {
        "algorithm": "sha256",
        "value": config.digest,
    }
    assert inference["configuration"] == config.to_dict()
    assert inference["extractor"] == {
        "identity": "goldilocks_core.ml.kdistance_features:extract_qrf_features",
        "feature_schema": "qrf-483-v1",
        "feature_count": 483,
    }
    assert inference["failure"] == {
        "stage": stage,
        "type": error.__class__.__name__,
        "message": str(error),
    }
    assert json.dumps(selection.to_dict(), allow_nan=False)
    return inference


def test_predict_kdistance_quantiles_returns_median_and_corrected_interval() -> None:
    """Median passes through; correction adjusts both interval bounds."""
    model = FakeQRF(lower=0.20, median=0.25, upper=0.30)

    median, lower, upper = predict_kdistance_quantiles(
        model, make_features(), correction=0.01
    )

    assert median == 0.25
    assert lower == 0.20 - 0.01
    assert upper == 0.30 + 0.01


def test_predict_kdistance_quantiles_rejects_wrong_quantile_count() -> None:
    """Reject a prediction that is not three quantiles."""

    class TwoQuantiles:
        def predict(self, X):
            return np.array([[0.2], [0.3]])

    with pytest.raises(ValueError, match="3 quantiles"):
        predict_kdistance_quantiles(TwoQuantiles(), make_features())


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ((0.2, np.nan, 0.3), "finite"),
        ((-0.2, 0.25, 0.3), "positive"),
        ((0.3, 0.25, 0.2), "lower <= median <= upper"),
    ],
)
def test_predict_kdistance_quantiles_rejects_invalid_values(values, message) -> None:
    """Reject invalid model output before converting a median to a mesh."""
    model = FakeQRF(*values)

    with pytest.raises(ValueError, match=message):
        predict_kdistance_quantiles(model, make_features())


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_predict_rejects_non_finite_features_before_calling_model(value) -> None:
    """NaN and both infinities are rejected immediately before prediction."""

    class PredictSpy:
        called = False

        def predict(self, X):
            self.called = True
            return np.array([[0.2], [0.25], [0.3]])

    model = PredictSpy()
    features = make_features()
    features.values[0] = value

    with pytest.raises(ValueError, match="features.*finite"):
        predict_kdistance_quantiles(model, features)

    assert model.called is False


def test_kdistance_to_selection_builds_grid_with_model_provenance() -> None:
    """Median distance sets the mesh; provenance records model and confidence."""
    selection = kdistance_to_selection(
        make_structure(),
        median=0.25,
        lower=0.19,
        upper=0.31,
        data_source="fixture-model@revision",
        confidence=0.95,
    )

    assert selection.grid == (7, 7, 7)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.95
    assert selection.provenance.data_source == "fixture-model@revision"


def test_packaged_registry_defines_versioned_default_artifacts() -> None:
    """Load pinned default model metadata from data rather than advisor source."""
    config = make_config()

    assert config.model.source == "huggingface"
    assert config.model.target == "k_distance"
    assert config.model.revision
    assert config.metallicity.revision
    assert config.metallicity_checkpoint_file
    assert config.metallicity_atom_init_file


def test_qrf_advisor_construction_does_not_load_models(monkeypatch) -> None:
    """Constructing the backend is free of model and network side effects."""
    calls = 0

    def count_load(spec):
        nonlocal calls
        calls += 1
        return FakeQRF(0.2, 0.25, 0.3)

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", count_load)

    qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    assert calls == 0


def test_direct_qrf_pipeline_requires_runtime_ownership() -> None:
    """Pipeline discovers the stateful QRF stage and rejects one-call execution."""
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")
    pipeline = Pipeline(kmesh=advisor)

    assert isinstance(advisor, RuntimeResource)
    assert pipeline.resources == (advisor,)
    with pytest.raises(ValueError, match="requires CoreRuntime ownership"):
        run_core_job(CoreJobRequest(structure=make_structure()), pipeline=pipeline)


def test_custom_qrf_pipeline_runtime_resets_and_closes_models(
    monkeypatch, tmp_path
) -> None:
    """Runtime ownership resets and closes a directly composed QRF backend."""
    checkpoint = tmp_path / "checkpoint.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    loads = 0
    model_references: list[weakref.ReferenceType[FakeQRF]] = []

    def load_model(spec):
        nonlocal loads
        loads += 1
        model = FakeQRF(0.2, 0.25, 0.3)
        model_references.append(weakref.ref(model))
        return model

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", load_model)
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model", lambda path: object()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=advisor))
    request = CoreJobRequest(structure=make_structure())

    runtime.run(request)
    runtime.run(request)
    runtime.reset()
    gc.collect()
    assert model_references[0]() is None

    runtime.run(request)
    runtime.close()
    gc.collect()

    assert loads == 2
    assert model_references[1]() is None
    with pytest.raises(RuntimeError, match="closed"):
        advisor(make_structure(), CalculationHints(), _make_advice())


def test_qrf_kdistance_advisor_predicts_with_model_provenance(
    monkeypatch, tmp_path
) -> None:
    """No hint: assemble features, run the QRF, and record model provenance."""
    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.25)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.9
    assert "@" in selection.provenance.data_source
    inference = selection.provenance.details["qrf_inference"]
    assert inference["config_digest"]["value"] == make_config().digest
    assert inference["extractor"]["feature_schema"] == "qrf-483-v1"


def test_qrf_kdistance_advisor_respects_grid_hint_without_loading(monkeypatch) -> None:
    """An explicit k-grid hint bypasses model loading and wins."""

    def unexpected_load(spec):
        raise AssertionError("explicit hints must not load a model")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", unexpected_load)
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    selection = advisor(
        make_structure(), CalculationHints(k_grid=(2, 2, 2)), _make_advice()
    )

    assert selection.grid == (2, 2, 2)
    assert selection.provenance.source == "user_hint"


def test_qrf_kdistance_advisor_rejects_incompatible_feature_contract(
    monkeypatch,
) -> None:
    """A hot-swapped model cannot silently change QRF feature semantics."""
    config = make_config()
    incompatible = replace(
        config,
        model=replace(config.model, feature_set="different-features"),
    )

    def unexpected_load(spec):
        raise AssertionError("incompatible configuration must fail before loading")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", unexpected_load)
    advisor = qrf_kdistance_advisor(incompatible, "ckpt.pkl", "atom.json")

    selection = advisor(make_structure(), CalculationHints(), _make_advice())

    assert selection.provenance.source == "fallback"
    _assert_qrf_failure_context(
        selection,
        incompatible,
        "schema",
        ValueError(
            "QRF advisor requires feature_set='qrf_comp_struct_soap_lattice_metal'; "
            "got 'different-features'."
        ),
    )
    assert any(
        "requires feature_set" in warning for warning in selection.provenance.warnings
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("feature_schema", "qrf-unknown", "feature_schema"),
        ("feature_count", 482, "feature_count"),
    ],
)
def test_qrf_advisor_rejects_extractor_schema_mismatch(
    monkeypatch, field, value, message
) -> None:
    config = replace(make_config(), **{field: value})

    def unexpected_load(spec):
        raise AssertionError("schema mismatch must fail before artifact loading")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", unexpected_load)
    selection = qrf_kdistance_advisor(config, "ckpt.pkl", "atom.json")(
        make_structure(), CalculationHints(), _make_advice()
    )

    assert selection.provenance.source == "fallback"
    _assert_qrf_failure_context(
        selection,
        config,
        "schema",
        ValueError(
            f"QRF extractor requires {field}="
            f"{('qrf-483-v1' if field == 'feature_schema' else 483)!r}; "
            f"got {value!r}."
        ),
    )
    assert any(message in warning for warning in selection.provenance.warnings)


def test_qrf_advisor_rejects_loaded_model_quantile_mismatch(
    monkeypatch,
    tmp_path,
) -> None:
    """Registry confidence cannot describe different model quantiles."""
    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    config = make_config()
    _patch_models(
        monkeypatch,
        FakeQRF(0.2, 0.25, 0.3, q=(0.025, 0.5, 0.975)),
    )

    selection = qrf_kdistance_advisor(
        config,
        str(checkpoint),
        str(atom_table),
    )(make_structure(), CalculationHints(), _make_advice())

    assert selection.provenance.source == "fallback"
    assert selection.provenance.details["qrf_inference"]["failure"]["stage"] == (
        "model_contract"
    )
    assert any(
        "quantiles do not match" in warning for warning in selection.provenance.warnings
    )


def test_qrf_advisor_rejects_runtime_mismatch_before_loading(monkeypatch) -> None:
    config = make_config()
    requirements = tuple(
        RuntimeRequirement(item.distribution, "0.0.0")
        if item.distribution == "matminer"
        else item
        for item in config.runtime_requirements
    )
    incompatible = replace(config, runtime_requirements=requirements)

    def unexpected_load(spec):
        raise AssertionError("runtime mismatch must fail before artifact loading")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", unexpected_load)
    selection = qrf_kdistance_advisor(incompatible, "ckpt.pkl", "atom.json")(
        make_structure(), CalculationHints(), _make_advice()
    )

    assert selection.provenance.source == "fallback"
    runtime = selection.provenance.details["qrf_inference"]["runtime"]
    installed_version = next(
        item["installed_version"]
        for item in runtime
        if item["distribution"] == "matminer"
    )
    inference = _assert_qrf_failure_context(
        selection,
        incompatible,
        "runtime",
        ValueError(f"QRF model requires matminer 0.0.0; found {installed_version}."),
    )
    assert all("required_version" in item for item in inference["runtime"])
    assert any("installed_version" not in item for item in inference["runtime"])
    assert any("matminer 0.0.0" in warning for warning in selection.provenance.warnings)


def test_qrf_advisor_preserves_partial_context_for_artifact_resolution_failure(
    monkeypatch,
    tmp_path,
) -> None:
    """Supporting-artifact failure retains the resolved preceding artifact."""
    checkpoint = tmp_path / "checkpoint.pkl"
    checkpoint.write_bytes(b"checkpoint")
    config = make_config()

    def resolve_artifact(spec, filename):
        if filename == config.metallicity_checkpoint_file:
            return str(checkpoint)
        raise FileNotFoundError("atom table is unavailable")

    monkeypatch.setattr("goldilocks_core.ml.models.resolve_artifact", resolve_artifact)
    selection = qrf_kdistance_advisor(config)(
        make_structure(), CalculationHints(), _make_advice()
    )

    assert selection.provenance.source == "fallback"
    inference = _assert_qrf_failure_context(
        selection,
        config,
        "artifact_resolution",
        FileNotFoundError("atom table is unavailable"),
    )
    assert all("installed_version" in item for item in inference["runtime"])
    assert inference["resolved_artifacts"] == [
        {"role": "metallicity_checkpoint", "path": str(checkpoint)}
    ]


def test_qrf_kdistance_advisor_caches_loaded_models(monkeypatch, tmp_path) -> None:
    """Successful model loading happens only on the first inference call."""
    calls = 0

    def count_load(spec):
        nonlocal calls
        calls += 1
        return FakeQRF(0.2, 0.25, 0.3)

    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    _patch_models(monkeypatch, FakeQRF(0.2, 0.25, 0.3))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", count_load)
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))

    advisor(make_structure(), CalculationHints(), _make_advice())
    advisor(make_structure(), CalculationHints(), _make_advice())

    assert calls == 1


def test_qrf_kdistance_advisor_loads_once_under_concurrency(
    monkeypatch, tmp_path
) -> None:
    """Concurrent first calls cannot race model success and failure state."""
    calls = 0
    start = Barrier(2)

    def count_load(spec):
        nonlocal calls
        calls += 1
        sleep(0.05)
        return FakeQRF(0.2, 0.25, 0.3)

    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    _patch_models(monkeypatch, FakeQRF(0.2, 0.25, 0.3))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", count_load)
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))

    def call_advisor():
        start.wait()
        return advisor(make_structure(), CalculationHints(), _make_advice())

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: call_advisor(), range(2)))

    assert calls == 1
    assert all(result.provenance.source == "model" for result in results)


def test_qrf_kdistance_advisor_caches_model_load_failure(monkeypatch, tmp_path) -> None:
    """A failed artifact load falls back without retrying on every structure."""
    calls = 0

    def boom(spec):
        nonlocal calls
        calls += 1
        raise ModuleNotFoundError("No module named 'torch'")

    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", boom)
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))

    first = advisor(make_structure(), CalculationHints(), _make_advice())
    second = advisor(make_structure(), CalculationHints(), _make_advice())

    assert calls == 1
    assert first.provenance.source == "fallback"
    assert second.provenance.source == "fallback"
    inference = _assert_qrf_failure_context(
        first,
        make_config(),
        "model_load",
        ModuleNotFoundError("No module named 'torch'"),
    )
    assert {artifact["role"] for artifact in inference["artifacts"]} == {
        "qrf_model",
        "metallicity_checkpoint",
        "metallicity_atom_table",
    }
    assert any("torch" in warning for warning in first.provenance.warnings)


def test_qrf_kdistance_advisor_falls_back_when_prediction_fails(
    monkeypatch, tmp_path
) -> None:
    """Per-structure inference errors fall back with a provenance warning."""
    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init, settings: (_ for _ in ()).throw(
            RuntimeError("feature extraction failed")
        ),
    )
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.2)
    assert selection.provenance.source == "fallback"
    _assert_qrf_failure_context(
        selection,
        make_config(),
        "prediction",
        RuntimeError("feature extraction failed"),
    )
    assert any(
        "feature extraction failed" in warning
        for warning in selection.provenance.warnings
    )


def test_qrf_kdistance_advisor_invalid_output_falls_back(monkeypatch, tmp_path) -> None:
    """Invalid QRF output never reaches mesh conversion."""
    checkpoint = tmp_path / "ckpt.pkl"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    _patch_models(monkeypatch, FakeQRF(lower=0.3, median=0.25, upper=0.2))
    advisor = qrf_kdistance_advisor(make_config(), str(checkpoint), str(atom_table))

    selection = advisor(make_structure(), CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(make_structure(), 0.2)
    assert selection.provenance.source == "fallback"
    assert any(
        "lower <= median <= upper" in warning
        for warning in selection.provenance.warnings
    )


def test_default_kmesh_advisor_honors_hint_with_invalid_registry(
    monkeypatch,
    tmp_path,
) -> None:
    """Hint-only jobs bypass both registry parsing and model loading."""
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(tmp_path / "missing.toml"))

    def unexpected_load(spec):
        raise AssertionError("explicit hints must not load a model")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", unexpected_load)
    advisor = default_kmesh_advisor()
    selection = advisor(
        make_structure(), CalculationHints(k_grid=(4, 4, 4)), _make_advice()
    )

    assert selection.grid == (4, 4, 4)
    assert selection.provenance.source == "user_hint"


def test_default_kmesh_advisor_preserves_unparsed_registry_failure_context(
    monkeypatch,
    tmp_path,
) -> None:
    """Malformed TOML does not invent an attempted QRF configuration."""
    invalid_registry = tmp_path / "invalid.toml"
    invalid_registry.write_text("[defaults.kpoints\n", encoding="utf-8")
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(invalid_registry))

    selection = default_kmesh_advisor()(
        make_structure(),
        CalculationHints(),
        _make_advice(),
    )

    assert selection.provenance.source == "fallback"
    inference = selection.provenance.details["qrf_inference"]
    assert inference["registry"] == {
        "status": "unparsed",
        "path": str(invalid_registry),
    }
    assert inference["failure"]["stage"] == "registry"
    assert inference["failure"]["type"] == "TOMLDecodeError"
    assert inference["failure"]["message"]
    assert "config_digest" not in inference
    assert "configuration" not in inference
    assert "extractor" not in inference
    assert json.dumps(selection.to_dict(), allow_nan=False)
    assert any(
        "Invalid value" in warning or "Expected" in warning
        for warning in selection.provenance.warnings
    )


def test_default_kmesh_advisor_resolves_configured_metallicity_artifacts(
    monkeypatch,
) -> None:
    """The default resolves supporting files from the loaded registry."""
    monkeypatch.delenv("GOLDILOCKS_METALLICITY_CHECKPOINT", raising=False)
    monkeypatch.delenv("GOLDILOCKS_METALLICITY_ATOM_INIT", raising=False)
    downloads: list[tuple[str, str, str | None]] = []

    def fake_download(*, repo_id, filename, revision):
        downloads.append((repo_id, filename, revision))
        return f"/cache/{repo_id}/{filename}"

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))

    config = make_config()
    advisor = default_kmesh_advisor(config=config)
    selection = advisor(make_structure(), CalculationHints(), _make_advice())

    assert selection.provenance.source == "model"
    assert {filename for _, filename, _ in downloads} == {
        config.metallicity_checkpoint_file,
        config.metallicity_atom_init_file,
    }
    assert {repo for repo, _, _ in downloads} == {config.metallicity.location}
    assert {revision for _, _, revision in downloads} == {config.metallicity.revision}
    inference = selection.provenance.details["qrf_inference"]
    artifacts = {item["role"]: item for item in inference["artifacts"]}
    assert artifacts["qrf_model"] == {
        "role": "qrf_model",
        "source": "huggingface",
        "repository": "STFC-SCD/kpoints-goldilocks-QRF",
        "filename": "QRF95.pkl",
        "revision": config.model.revision,
    }
    assert artifacts["metallicity_checkpoint"]["repository"] == (
        config.metallicity.location
    )
    assert artifacts["metallicity_checkpoint"]["filename"] == (
        config.metallicity_checkpoint_file
    )
    assert artifacts["metallicity_atom_table"]["filename"] == (
        config.metallicity_atom_init_file
    )
    assert json.dumps(selection.to_dict(), allow_nan=False)


def test_local_qrf_artifacts_use_sha256_content_identities(
    monkeypatch, tmp_path
) -> None:
    """Mutable local paths are supplemented by hashes of all three files."""
    qrf_path = tmp_path / "qrf.joblib"
    checkpoint = tmp_path / "metal.ckpt"
    atom_table = tmp_path / "atom.json"
    qrf_path.write_bytes(b"local qrf")
    checkpoint.write_bytes(b"local checkpoint")
    atom_table.write_bytes(b"local atom table")

    config = make_config()
    local_config = replace(
        config,
        model=replace(
            config.model,
            source="local",
            location=str(qrf_path),
            revision=None,
        ),
    )
    _patch_models(monkeypatch, FakeQRF(0.2, 0.25, 0.3))
    selection = qrf_kdistance_advisor(
        local_config,
        str(checkpoint),
        str(atom_table),
    )(make_structure(), CalculationHints(), _make_advice())

    artifacts = {
        item["role"]: item
        for item in selection.provenance.details["qrf_inference"]["artifacts"]
    }
    assert artifacts["qrf_model"]["sha256"] == hashlib.sha256(b"local qrf").hexdigest()
    assert (
        artifacts["metallicity_checkpoint"]["sha256"]
        == hashlib.sha256(b"local checkpoint").hexdigest()
    )
    assert (
        artifacts["metallicity_atom_table"]["sha256"]
        == hashlib.sha256(b"local atom table").hexdigest()
    )


def test_local_atom_table_mutation_is_rejected(monkeypatch, tmp_path) -> None:
    """Cached provenance cannot describe different atom-table content."""
    checkpoint = tmp_path / "metal.ckpt"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"local checkpoint")
    atom_table.write_bytes(b"original atom table")
    _patch_models(monkeypatch, FakeQRF(0.2, 0.25, 0.3))
    advisor = qrf_kdistance_advisor(
        make_config(),
        str(checkpoint),
        str(atom_table),
    )

    first = advisor(make_structure(), CalculationHints(), _make_advice())
    atom_table.write_bytes(b"changed atom table")
    second = advisor(make_structure(), CalculationHints(), _make_advice())

    assert first.provenance.source == "model"
    assert second.provenance.source == "fallback"
    assert second.provenance.details["qrf_inference"]["failure"]["stage"] == (
        "prediction"
    )
    assert any("atom table changed" in item for item in second.provenance.warnings)
