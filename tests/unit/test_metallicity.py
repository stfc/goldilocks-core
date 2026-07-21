from __future__ import annotations

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml import cgcnn, metallicity


def test_load_metallicity_model_reconstructs_checkpoint_and_enters_eval_mode(
    monkeypatch,
) -> None:
    """Verify checkpoint parameters and Lightning weight prefixes at the boundary."""
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
    """Verify feature extraction passes graph controls and returns a flat array."""
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    atom_features = np.array([[1.0, 2.0]])
    graph = object()
    calls = {}

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(no_grad=nullcontext),
    )
    monkeypatch.setattr(
        metallicity,
        "atom_features_from_structure",
        lambda actual_structure, path: (
            calls.update(structure=actual_structure, path=path) or atom_features
        ),
    )

    def build_graph(actual_structure, actual_features, *, radius, max_neighbors):
        calls.update(
            graph_structure=actual_structure,
            features=actual_features,
            radius=radius,
            max_neighbors=max_neighbors,
        )
        return graph

    monkeypatch.setattr(
        metallicity,
        "build_radius_cgcnn_graph_from_structure",
        build_graph,
    )

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
        "graph_structure": structure,
        "features": atom_features,
        "radius": 8.0,
        "max_neighbors": 12,
        "model_graph": graph,
    }
