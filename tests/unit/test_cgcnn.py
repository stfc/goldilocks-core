import json

import pytest
import torch
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.qrf.atom_features import atom_features_from_structure
from goldilocks_core.ml.qrf.cgcnn import CGCNN_PyG
from goldilocks_core.ml.qrf.cgcnn_graph import build_radius_cgcnn_graph_from_structure


def make_pair() -> Structure:
    return Structure(
        Lattice.cubic(3.0), ["Si", "Si"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
    )


def test_atom_features_from_structure_looks_up_embeddings(tmp_path) -> None:
    atom_init = tmp_path / "atom_init.json"
    atom_init.write_text(json.dumps({"14": [1.0, 2.0, 3.0]}))  # Si = 14

    features = atom_features_from_structure(make_pair(), str(atom_init))

    assert features == [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]


def test_atom_features_missing_element_raises(tmp_path) -> None:
    atom_init = tmp_path / "atom_init.json"
    atom_init.write_text(json.dumps({"14": [1.0]}))  # no oxygen
    structure = Structure(Lattice.cubic(4.0), ["O"], [[0.0, 0.0, 0.0]])

    with pytest.raises(ValueError, match="No atom embedding"):
        atom_features_from_structure(structure, str(atom_init))


def test_build_radius_graph_has_expected_shapes() -> None:
    data = build_radius_cgcnn_graph_from_structure(
        make_pair(), [[1.0, 0.0], [0.0, 1.0]], radius=5.0
    )

    assert data.x.shape == (2, 2)
    assert data.edge_index.shape[0] == 2
    assert data.edge_index.shape[1] == data.edge_attr.shape[0]
    assert data.edge_attr.shape[1] == 1


def make_graph():
    return build_radius_cgcnn_graph_from_structure(
        make_pair(), [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], radius=5.0
    )


def test_cgcnn_extract_crystal_repr_pools_to_atom_fea_len() -> None:
    model = CGCNN_PyG(
        orig_atom_fea_len=4, atom_fea_len=8, edge_feat_dim=16, n_conv=1, n_h=1
    )
    model.eval()

    with torch.no_grad():
        representation = model.extract_crystal_repr(make_graph())

    assert representation.shape == (1, 8)
    assert torch.isfinite(representation).all()


def test_cgcnn_forward_returns_class_probabilities() -> None:
    model = CGCNN_PyG(
        orig_atom_fea_len=4,
        atom_fea_len=8,
        edge_feat_dim=16,
        h_fea_len=10,
        n_conv=1,
        n_h=2,
        classification=True,
    )
    model.eval()

    with torch.no_grad():
        probabilities = model(make_graph())

    assert probabilities.shape == (1, 2)
    assert torch.allclose(probabilities.sum(dim=1), torch.ones(1))


def test_cgcnn_forward_projects_additional_compound_features() -> None:
    model = CGCNN_PyG(
        orig_atom_fea_len=4,
        atom_fea_len=8,
        edge_feat_dim=16,
        h_fea_len=10,
        n_conv=1,
        n_h=1,
        classification=True,
        additional_compound_features=True,
        add_feat_len=3,
    )
    model.eval()

    with torch.no_grad():
        probabilities = model(make_graph(), torch.tensor([[1.0, 2.0, 3.0]]))

    assert probabilities.shape == (1, 2)
    assert torch.allclose(probabilities.sum(dim=1), torch.ones(1))
