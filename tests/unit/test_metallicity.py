from __future__ import annotations

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.qrf import cgcnn, metallicity


def test_load_metallicity_model_reconstructs_checkpoint_and_enters_eval_mode(
    monkeypatch,
) -> None:
    checkpoint = {
        "hyper_parameters": {"model": {"atom_fea_len": 8}},
        "state_dict": {"model.layer.weight": "weights", "model.bias": "bias"},
    }
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            load=lambda path, **kwargs: checkpoint,
            no_grad=nullcontext,
        ),
    )

    class FakeModel:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.weights = None
            self.eval_called = False

        def load_state_dict(self, weights) -> None:
            self.weights = weights

        def eval(self) -> None:
            self.eval_called = True

    monkeypatch.setattr(cgcnn, "CGCNN_PyG", FakeModel)

    model = metallicity.load_metallicity_model("checkpoint.ckpt")

    assert model.kwargs == {"atom_fea_len": 8}
    assert model.weights == {"layer.weight": "weights", "bias": "bias"}
    assert model.eval_called is True


def test_probability_mapping_uses_published_class_order() -> None:
    assert metallicity._electronic_character_from_probabilities([0.8, 0.2]) == (
        "insulator",
        0.8,
    )
    assert metallicity._electronic_character_from_probabilities([0.1, 0.9]) == (
        "metal",
        0.9,
    )


def test_metal_features_builds_configured_graph_without_gradients(monkeypatch) -> None:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    graph = object()
    calls = {}

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(no_grad=nullcontext),
    )

    def build_graph(actual_structure, path, *, graph_radius, max_neighbors):
        calls.update(
            structure=actual_structure,
            path=path,
            graph_radius=graph_radius,
            max_neighbors=max_neighbors,
        )
        return graph

    monkeypatch.setattr(metallicity, "_build_graph", build_graph)

    class FakeRepresentation:
        def numpy(self) -> np.ndarray:
            return np.array([[3.0, 4.0]])

    class FakeModel:
        def extract_crystal_repr(self, actual_graph):
            calls["model_graph"] = actual_graph
            return FakeRepresentation()

    result = metallicity.metal_features(
        structure,
        FakeModel(),
        "atom_init.json",
        graph_radius=8.0,
        max_neighbors=12,
    )

    assert np.array_equal(result, np.array([3.0, 4.0]))
    assert calls == {
        "structure": structure,
        "path": "atom_init.json",
        "graph_radius": 8.0,
        "max_neighbors": 12,
        "model_graph": graph,
    }


def test_classify_metallicity_runs_full_model_forward(monkeypatch) -> None:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    graph = object()
    calls = {}
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=nullcontext))
    monkeypatch.setattr(metallicity, "_build_graph", lambda *args, **kwargs: graph)

    class FakeProbabilities:
        def numpy(self) -> np.ndarray:
            return np.array([[0.25, 0.75]])

    class FakeModel:
        def __call__(self, actual_graph):
            calls["graph"] = actual_graph
            return FakeProbabilities()

    result = metallicity.classify_metallicity(
        structure,
        FakeModel(),
        "atom_init.json",
        graph_radius=10.0,
        max_neighbors=12,
    )

    assert result == ("metal", 0.75)
    assert calls == {"graph": graph}
