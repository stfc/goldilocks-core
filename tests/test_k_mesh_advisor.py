from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.kmesh_advisor import advise_kpoints, ml_kmesh_advisor
from goldilocks_core.contracts import (
    CalculationHints,
    KPointAdvice,
    ModelSpec,
    Provenance,
)


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


def make_advice() -> KPointAdvice:
    """Build default k-point advice for Kmesh backend tests."""
    return KPointAdvice(
        spacing=0.25,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="default", reason="default spacing"),
    )


def test_advise_kpoints_returns_selected_mesh(monkeypatch) -> None:
    """Advise a k-point mesh from a predicted k-index."""
    structure = make_structure()
    spec = make_spec()

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


def test_ml_kmesh_advisor_uses_model_when_no_hint_is_set(monkeypatch) -> None:
    """Expose ML k-points as a first-class Kmesh-stage backend."""
    structure = make_structure()
    spec = make_spec()
    monkeypatch.setattr(
        "goldilocks_core.advisors.kmesh_advisor.load_model",
        lambda _: DummyModel(),
    )

    selection = ml_kmesh_advisor(spec)(structure, CalculationHints(), make_advice())

    assert selection.grid == (3, 3, 3)
    assert selection.provenance.source == "model"
    assert selection.provenance.data_source == spec.name


def test_ml_kmesh_advisor_prefers_explicit_grid_hint(monkeypatch) -> None:
    """Operator grid hints override model-backed k-point selection."""
    structure = make_structure()
    spec = make_spec()
    called = False

    def fail_if_called(_):
        nonlocal called
        called = True
        return DummyModel()

    monkeypatch.setattr(
        "goldilocks_core.advisors.kmesh_advisor.load_model",
        fail_if_called,
    )

    selection = ml_kmesh_advisor(spec)(
        structure,
        CalculationHints(k_grid=(1, 2, 3)),
        make_advice(),
    )

    assert called is False
    assert selection.grid == (1, 2, 3)
    assert selection.provenance.source == "user_hint"


def test_ml_kmesh_advisor_prefers_spacing_hint(monkeypatch) -> None:
    """Operator spacing hints override model-backed k-point selection."""
    structure = make_structure()
    spec = make_spec()
    called = False

    def fail_if_called(_):
        nonlocal called
        called = True
        return DummyModel()

    monkeypatch.setattr(
        "goldilocks_core.advisors.kmesh_advisor.load_model",
        fail_if_called,
    )

    selection = ml_kmesh_advisor(spec)(
        structure,
        CalculationHints(k_spacing=0.5),
        make_advice(),
    )

    assert called is False
    assert selection.grid == (4, 4, 4)
    assert selection.provenance.source == "user_hint"
