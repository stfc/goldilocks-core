import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.kdistance_advisor import (
    DEFAULT_KPOINTS_MODEL,
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


def test_predict_kdistance_quantiles_returns_median_and_corrected_interval() -> None:
    """Median passes through; correction widens the interval bounds."""
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

    try:
        predict_kdistance_quantiles(TwoQuantiles(), make_features())
    except ValueError as error:
        assert "3 quantiles" in str(error)
    else:
        raise AssertionError("expected ValueError for wrong quantile count")


def test_kdistance_to_selection_builds_grid_with_model_provenance() -> None:
    """Median distance sets the mesh; provenance records model + confidence."""
    selection = kdistance_to_selection(
        make_structure(),
        median=0.25,
        lower=0.19,
        upper=0.31,
        data_source="kpoints-goldilocks-QRF",
        confidence=0.95,
    )

    assert selection.grid == (7, 7, 7)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.95
    assert selection.provenance.data_source == "kpoints-goldilocks-QRF"


def test_default_kpoints_model_targets_hf_qrf95() -> None:
    """The built-in default resolves the QRF95 artifact from Hugging Face."""
    assert DEFAULT_KPOINTS_MODEL.source == "huggingface"
    assert DEFAULT_KPOINTS_MODEL.location.endswith("::QRF95.pkl")
    assert DEFAULT_KPOINTS_MODEL.target == "k_distance"


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


def test_qrf_kdistance_advisor_predicts_with_model_provenance(monkeypatch) -> None:
    """No hint: assemble features, run the QRF, and record model provenance."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json", correction=0.0)

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.25)
    assert selection.provenance.source == "model"
    assert selection.provenance.confidence == 0.95


def test_qrf_kdistance_advisor_respects_grid_hint(monkeypatch) -> None:
    """An explicit k-grid hint bypasses the model and wins."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json")

    selection = advisor(
        make_structure(), CalculationHints(k_grid=(2, 2, 2)), _make_advice()
    )

    assert selection.grid == (2, 2, 2)
    assert selection.provenance.source == "user_hint"


def test_qrf_kdistance_advisor_falls_back_when_model_load_fails(monkeypatch) -> None:
    """Missing deps/checkpoint: degrade to heuristic advice, warn, never crash."""

    def boom(spec):
        raise ModuleNotFoundError("No module named 'torch'")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", boom)
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json")

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    # Mesh comes from the heuristic advice (spacing 0.2), not the model.
    assert selection.grid == k_distance_to_mesh(structure, 0.2)
    assert selection.provenance.source != "model"
    assert any("torch" in warning for warning in selection.provenance.warnings)


def test_qrf_kdistance_advisor_falls_back_when_prediction_fails(monkeypatch) -> None:
    """Model loads but per-structure inference raises: fall back with a warning."""
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init: (_ for _ in ()).throw(
            RuntimeError("feature extraction failed")
        ),
    )
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json")

    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.2)
    assert selection.provenance.source != "model"
    assert any(
        "feature extraction failed" in warning
        for warning in selection.provenance.warnings
    )


def test_qrf_kdistance_advisor_load_failure_still_honors_grid_hint(monkeypatch) -> None:
    """Even with the model unavailable, an explicit grid hint wins cleanly."""

    def boom(spec):
        raise ModuleNotFoundError("No module named 'torch'")

    monkeypatch.setattr("goldilocks_core.ml.models.load_model", boom)
    advisor = qrf_kdistance_advisor("ckpt.pkl", "atom.json")

    selection = advisor(
        make_structure(), CalculationHints(k_grid=(2, 2, 2)), _make_advice()
    )

    assert selection.grid == (2, 2, 2)
    assert selection.provenance.source == "user_hint"
    assert selection.provenance.warnings == ()


def test_default_kmesh_advisor_falls_back_without_checkpoint(
    monkeypatch, tmp_path
) -> None:
    """The built-in default degrades to heuristic advice when nothing resolves."""
    monkeypatch.setenv(
        "GOLDILOCKS_METALLICITY_CHECKPOINT", str(tmp_path / "missing.ckpt")
    )
    monkeypatch.setenv(
        "GOLDILOCKS_METALLICITY_ATOM_INIT", str(tmp_path / "missing.json")
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda spec: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    advisor = default_kmesh_advisor()
    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.grid == k_distance_to_mesh(structure, 0.2)
    assert selection.provenance.source != "model"
    assert selection.provenance.warnings


def test_default_kmesh_advisor_honors_explicit_grid_hint(monkeypatch) -> None:
    """An explicit grid hint wins even for the built-in default backend."""
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda spec: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    advisor = default_kmesh_advisor()
    selection = advisor(
        make_structure(), CalculationHints(k_grid=(4, 4, 4)), _make_advice()
    )

    assert selection.grid == (4, 4, 4)
    assert selection.provenance.source == "user_hint"


def test_default_kmesh_advisor_downloads_metallicity_from_hf(monkeypatch) -> None:
    """With no local override, the default resolves the checkpoint from HF."""
    monkeypatch.delenv("GOLDILOCKS_METALLICITY_CHECKPOINT", raising=False)
    monkeypatch.delenv("GOLDILOCKS_METALLICITY_ATOM_INIT", raising=False)
    monkeypatch.delenv("GOLDILOCKS_METALLICITY_REPO", raising=False)

    downloads: list[tuple[str, str]] = []

    def fake_download(repo_id, filename, revision=None):
        downloads.append((repo_id, filename))
        return f"/cache/{repo_id}/{filename}"

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    _patch_models(monkeypatch, FakeQRF(lower=0.20, median=0.25, upper=0.30))

    advisor = default_kmesh_advisor()
    structure = make_structure()
    selection = advisor(structure, CalculationHints(), _make_advice())

    assert selection.provenance.source == "model"
    downloaded_files = {filename for _, filename in downloads}
    assert downloaded_files == {"is_metal.ckpt", "atom_init.json"}
    repos = {repo for repo, _ in downloads}
    assert repos == {"JunwenYin/metallicity-goldilocks-CGCNN"}
