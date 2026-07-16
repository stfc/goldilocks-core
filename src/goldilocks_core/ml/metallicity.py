"""Pretrained CGCNN metallicity model: loading and crystal-representation features.

The QRF k-distance feature vector includes a "metal" block: the pooled crystal
representation from a CGCNN metallicity classifier. The same model is the basis
for a future Analyze-stage metallicity prediction. The heavy torch dependency
is imported lazily.
"""

from __future__ import annotations

import numpy as np
from pymatgen.core.structure import Structure

from goldilocks_core.ml.atom_features import atom_features_from_structure
from goldilocks_core.ml.cgcnn_graph import build_radius_cgcnn_graph_from_structure


def load_metallicity_model(checkpoint_path: str) -> object:
    """Load the pretrained CGCNN metallicity model from a Lightning checkpoint.

    Reconstructs ``CGCNN_PyG`` from the checkpoint's hyper-parameters and loads
    the weights (stripping the Lightning ``model.`` prefix). Returns the model
    in eval mode.
    """
    import torch

    from goldilocks_core.ml.cgcnn import CGCNN_PyG

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = CGCNN_PyG(**checkpoint["hyper_parameters"]["model"])
    weights = {
        key.replace("model.", ""): value
        for key, value in checkpoint["state_dict"].items()
    }
    model.load_state_dict(weights)
    model.eval()
    return model


def metal_features(
    structure: Structure,
    model: object,
    atom_init_path: str,
) -> np.ndarray:
    """Return the CGCNN pooled crystal representation for ``structure`` (1-D)."""
    import torch

    atom_feats = atom_features_from_structure(structure, atom_init_path)
    graph = build_radius_cgcnn_graph_from_structure(structure, atom_feats)
    with torch.no_grad():
        representation = model.extract_crystal_repr(graph)
    return representation.numpy().reshape(-1)
