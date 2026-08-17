from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.kindex import advise_kpoints, ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec


class DummyModel:
    """Minimal model that predicts a fixed k-index."""

    def predict(self, X):
        return [2.2]


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_spec() -> ModelSpec:
    """Build a local k-mesh model spec for tests."""
    return ModelSpec(
        name="dummy-kmesh-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location="unused.joblib",
        revision=None,
    )


def test_advise_kpoints_returns_selected_mesh(monkeypatch) -> None:
    """Advise a k-point mesh from a predicted k-index."""
    structure = make_structure()
    spec = make_spec()

    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda _: DummyModel(),
    )

    advice = advise_kpoints(structure, spec)

    assert advice.mesh_type == "monkhorst-pack"
    assert advice.grid == (3, 3, 3)
    assert advice.shift == (0, 0, 0)
    assert advice.provenance.source == "model"
    assert advice.provenance.data_source == spec.name


def test_ml_kmesh_advisor_uses_model_when_invoked(monkeypatch) -> None:
    """Expose ML k-points as a first-class Kmesh-stage backend."""
    structure = make_structure()
    spec = make_spec()
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda _: DummyModel(),
    )

    selection = ml_kmesh_advisor(spec)(structure)

    assert selection.grid == (3, 3, 3)
    assert selection.provenance.source == "model"
    assert selection.provenance.data_source == spec.name
