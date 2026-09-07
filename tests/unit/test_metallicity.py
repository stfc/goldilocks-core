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
