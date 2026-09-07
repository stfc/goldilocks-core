from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.kindex import advise_kpoints, ml_kmesh_advisor
from goldilocks_core.contracts import PREDICTION_RESOLVERS, ModelSpec


class StubModel:
    """Stands in for a loaded goldilocks-ml k-index model. ``k_index`` is a
    rung on Core's own ladder (rung 1 = Gamma-only) -- there is exactly one
    k_index numbering in this system, so nothing else needs to be told."""

    def __init__(self, k_index: float = 3) -> None:
        self.k_index = k_index

    def predict(self, structure):
        from goldilocks_ml.inference import ModelPrediction

        return ModelPrediction(
            parameter="k_points",
            quantity="k_index",
            value=self.k_index,
            target_contract="goldilocks.k_index.ladder_1based.max50.v1",
            model_id="k_points.k_index.qrf@cslr.v1",
            details={"max_kpoints_per_axis": 50},
        )


def make_structure() -> Structure:
    return Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_spec() -> ModelSpec:
    return ModelSpec(
        name="dummy-kmesh-model",
        version="v0",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location="unused-model-dir",
        revision=None,
    )


def test_k_points_resolver_is_registered() -> None:
    assert "k_points" in PREDICTION_RESOLVERS


def test_advise_kpoints_returns_selected_mesh(monkeypatch) -> None:
    structure = make_structure()
    spec = make_spec()

    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda _: StubModel(k_index=3),
    )

    advice = advise_kpoints(structure, spec)

    assert advice.mesh_type == "monkhorst-pack"
    assert advice.grid == (3, 3, 3)
    assert advice.shift == (0, 0, 0)
    assert advice.provenance.source == "model"
    assert advice.provenance.data_source == "k_points.k_index.qrf@cslr.v1"


def test_ml_kmesh_advisor_uses_model_when_invoked(monkeypatch) -> None:
    structure = make_structure()
    spec = make_spec()
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda _: StubModel(k_index=3),
    )

    selection = ml_kmesh_advisor(spec)(structure)

    assert selection.grid == (3, 3, 3)
    assert selection.provenance.source == "model"


def test_rung_one_is_the_gamma_only_mesh(monkeypatch) -> None:
    """The base of the ladder, which an off-by-one moves and nothing else does."""
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda _: StubModel(k_index=1),
    )

    advice = advise_kpoints(make_structure(), make_spec())

    assert advice.grid == (1, 1, 1)


def test_a_fractional_prediction_rounds_up_to_the_next_rung(monkeypatch) -> None:
    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda _: StubModel(k_index=2.2),
    )

    advice = advise_kpoints(make_structure(), make_spec())

    assert advice.grid == (3, 3, 3)
