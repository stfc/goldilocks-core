import json

import pytest
import torch
from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.atom_features import atom_features_from_structure
from goldilocks_core.ml.cgcnn import CGCNN_PyG
from goldilocks_core.ml.cgcnn_graph import build_radius_cgcnn_graph_from_structure


def make_pair() -> Structure:
    return Structure(
        Lattice.cubic(3.0), ["Si", "Si"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
    )


def test_atom_features_from_structure_looks_up_embeddings(tmp_path) -> None:
    """Each atom gets its embedding by atomic number from the atom_init map."""
    atom_init = tmp_path / "atom_init.json"
    atom_init.write_text(json.dumps({"14": [1.0, 2.0, 3.0]}))  # Si = 14

    features = atom_features_from_structure(make_pair(), str(atom_init))

    assert features == [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]


def test_atom_features_missing_element_raises(tmp_path) -> None:
    """A missing element in the embedding map is a clear error."""
    atom_init = tmp_path / "atom_init.json"
    atom_init.write_text(json.dumps({"14": [1.0]}))  # no oxygen
    structure = Structure(Lattice.cubic(4.0), ["O"], [[0.0, 0.0, 0.0]])

    with pytest.raises(ValueError, match="No atom embedding"):
        atom_features_from_structure(structure, str(atom_init))


def test_build_radius_graph_has_expected_shapes() -> None:
    """The graph carries node features, a 2xE edge index, and scalar distances."""
    data = build_radius_cgcnn_graph_from_structure(
        make_pair(), [[1.0, 0.0], [0.0, 1.0]], radius=5.0
    )

    assert data.x.shape == (2, 2)
    assert data.edge_index.shape[0] == 2
    assert data.edge_index.shape[1] == data.edge_attr.shape[0]
    assert data.edge_attr.shape[1] == 1


def test_cgcnn_extract_crystal_repr_pools_to_atom_fea_len() -> None:
    """The pooled crystal representation has width atom_fea_len for one graph."""
    model = CGCNN_PyG(
        orig_atom_fea_len=4, atom_fea_len=8, edge_feat_dim=16, n_conv=1, n_h=1
    )
    model.eval()
    data = build_radius_cgcnn_graph_from_structure(
        make_pair(), [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], radius=5.0
    )

    with torch.no_grad():
        representation = model.extract_crystal_repr(data)

    assert representation.shape == (1, 8)
    assert torch.isfinite(representation).all()
