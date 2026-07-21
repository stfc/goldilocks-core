from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from time import sleep

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

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
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh
from goldilocks_core.ml.model_registry import (
    MODEL_REGISTRY_ENV,
    load_default_qrf_config,
)


class FakeQRF:
    """Minimal QRF stub returning fixed (lower, median, upper) quantiles."""

    def __init__(self, lower, median, upper):
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
        lambda structure, model, atom_init: StructureFeatureVector(
            values=np.zeros(483), feature_names=[]
        ),
    )


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


def test_qrf_kdistance_advisor_predicts_with_model_provenance(monkeypatch) -> None:
    """No hint: assemble features, run the QRF, and record model provenance."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.25)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.95
    assert "@" in selection.provenance.data_source


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

    assert selection.provenance.source != "model"
    assert any(
        "requires feature_set" in warning for warning in selection.provenance.warnings
    )


def test_qrf_kdistance_advisor_caches_loaded_models(monkeypatch) -> None:
    """Successful model loading happens only on the first inference call."""
    calls = 0

    def count_load(spec):
        nonlocal calls
        calls += 1
        return FakeQRF(0.2, 0.25, 0.3)

    _patch_models(monkeypatch, FakeQRF(0.2, 0.25, 0.3))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", count_load)
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    advisor(make_structure(), CalculationHints(), _make_advice())
    advisor(make_structure(), CalculationHints(), _make_advice())

    assert calls == 1


def test_qrf_kdistance_advisor_loads_once_under_concurrency(monkeypatch) -> None:
    """Concurrent first calls cannot race model success and failure state."""
    calls = 0
    start = Barrier(2)

    def count_load(spec):
        nonlocal calls
        calls += 1
        sleep(0.05)
        return FakeQRF(0.2, 0.25, 0.3)

    _patch_models(monkeypatch, FakeQRF(0.2, 0.25, 0.3))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", count_load)
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    def call_advisor():
        start.wait()
        return advisor(make_structure(), CalculationHints(), _make_advice())

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: call_advisor(), range(2)))

    assert calls == 1
    assert all(result.provenance.source == "model" for result in results)


def test_qrf_kdistance_advisor_caches_model_load_failure(monkeypatch) -> None:
    """A failed artifact load falls back without retrying on every structure."""
    calls = 0

    def boom(spec):
        nonlocal calls
        calls += 1
        raise ModuleNotFoundError("No module named 'torch'")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", boom)
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    first = advisor(make_structure(), CalculationHints(), _make_advice())
    second = advisor(make_structure(), CalculationHints(), _make_advice())

    assert calls == 1
    assert first.provenance.source != "model"
    assert second.provenance.source != "model"
    assert any("torch" in warning for warning in first.provenance.warnings)


def test_qrf_kdistance_advisor_falls_back_when_prediction_fails(monkeypatch) -> None:
    """Per-structure inference errors fall back with a provenance warning."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init: (_ for _ in ()).throw(
            RuntimeError("feature extraction failed")
        ),
    )
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.2)
    assert selection.provenance.source != "model"
    assert any(
        "feature extraction failed" in warning
        for warning in selection.provenance.warnings
    )


def test_qrf_kdistance_advisor_invalid_output_falls_back(monkeypatch) -> None:
    """Invalid QRF output never reaches mesh conversion."""
    _patch_models(monkeypatch, FakeQRF(lower=0.3, median=0.25, upper=0.2))
    advisor = qrf_kdistance_advisor(make_config(), "ckpt.pkl", "atom.json")

    selection = advisor(make_structure(), CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(make_structure(), 0.2)
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


def test_default_kmesh_advisor_falls_back_for_invalid_registry(
    monkeypatch,
    tmp_path,
) -> None:
    """A registry error becomes an actionable heuristic fallback warning."""
    missing_registry = tmp_path / "missing.toml"
    monkeypatch.setenv(MODEL_REGISTRY_ENV, str(missing_registry))

    selection = default_kmesh_advisor()(
        make_structure(),
        CalculationHints(),
        _make_advice(),
    )

    assert selection.provenance.source != "model"
    assert any(
        str(missing_registry) in warning for warning in selection.provenance.warnings
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
    data_source = selection.provenance.data_source
    assert config.model.location in data_source
    assert config.model.revision in data_source
    assert config.metallicity.location in data_source
    assert config.metallicity.revision in data_source
    assert config.metallicity_checkpoint_file in data_source
    assert config.metallicity_atom_init_file in data_source
