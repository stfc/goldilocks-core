from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.kmesh_advisor import advise_kpoints
from goldilocks_core.contracts import ModelSpec


class DummyModel:
    """Minimal model that predicts a fixed k-index."""

    def predict(self, X):
        return [2.2]


def test_advise_kpoints_returns_selected_mesh(monkeypatch) -> None:
    """Advise a k-point mesh from a predicted k-index."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )

    spec = ModelSpec(
        name="dummy-kmesh-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location="unused.joblib",
        revision=None,
    )

    monkeypatch.setattr(
        "goldilocks_core.advisors.kmesh_advisor.load_model",
        lambda _: DummyModel(),
    )

    advice = advise_kpoints(structure, spec)

    assert advice.mesh_type == "monkhorst-pack"
    assert advice.grid == (3, 3, 3)
    assert advice.shift == (0, 0, 0)
    assert advice.provenance.source == "model"
    assert advice.provenance.data_source == spec.name
