from dataclasses import replace

from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.kindex import advise_kpoints, ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec


class DummyModel:
    # The deployed model publishes whole rungs. A fractional prediction is
    # rounded up before it indexes the ladder, and the arithmetic that does
    # that happens to survive an off-by-one in the base; an integer does not.
    def __init__(self, k_index: float = 3):
        self.k_index = k_index

    def predict(self, X):
        return [self.k_index]


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
        location="unused.joblib",
        revision=None,
    )


def test_advise_kpoints_returns_selected_mesh(monkeypatch) -> None:
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


def test_rung_one_is_the_gamma_only_mesh(monkeypatch) -> None:
    """The base of the ladder, which an off-by-one moves and nothing else does."""
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda _: DummyModel(k_index=1),
    )

    advice = advise_kpoints(make_structure(), make_spec())

    assert advice.grid == (1, 1, 1)


def test_a_fractional_prediction_rounds_up_to_the_next_rung(monkeypatch) -> None:
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda _: DummyModel(k_index=2.2),
    )

    advice = advise_kpoints(make_structure(), make_spec())

    assert advice.grid == (3, 3, 3)


def test_a_zero_based_record_still_names_the_same_mesh(monkeypatch) -> None:
    """The published k-index model numbers the Gamma-only mesh 0, not 1.

    Its rung 2 and this ladder's rung 3 are the same mesh, and a consumer that
    ignored the base would quietly serve one rung too coarse.
    """
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda _: DummyModel(k_index=2),
    )
    spec = replace(make_spec(), k_index_base=0)

    advice = advise_kpoints(make_structure(), spec)

    assert advice.grid == (3, 3, 3)


def test_a_zero_based_gamma_rung_is_the_gamma_mesh(monkeypatch) -> None:
    monkeypatch.setattr(
        "goldilocks_core.ml.models.load_model",
        lambda _: DummyModel(k_index=0),
    )
    spec = replace(make_spec(), k_index_base=0)

    advice = advise_kpoints(make_structure(), spec)

    assert advice.grid == (1, 1, 1)
