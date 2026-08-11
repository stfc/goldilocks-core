"""Pretrained CGCNN metallicity model: loading and crystal-representation features.

The QRF k-distance feature vector includes a "metal" block: the pooled crystal
representation from a CGCNN metallicity classifier. The same model provides
Analyze-stage metallicity predictions. The heavy torch dependency is imported
lazily.
"""

from __future__ import annotations

import numpy as np
from pymatgen.core.structure import Structure

from goldilocks_core.contracts import ElectronicCharacter


def load_metallicity_model(checkpoint_path: str) -> object:
    """Load the pretrained CGCNN metallicity model from a Lightning checkpoint.

    Reconstructs ``CGCNN_PyG`` from the checkpoint's hyper-parameters and loads
    the weights (stripping the Lightning ``model.`` prefix). Returns the model
    in eval mode.
    """
    import torch

    from .cgcnn import CGCNN_PyG

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = CGCNN_PyG(**checkpoint["hyper_parameters"]["model"])
    weights = {
        key.replace("model.", ""): value
        for key, value in checkpoint["state_dict"].items()
    }
    model.load_state_dict(weights)
    model.eval()
    return model


def _build_graph(
    structure: Structure,
    atom_init_path: str,
    *,
    graph_radius: float,
    max_neighbors: int,
) -> object:
    """Build the configured CGCNN graph for one structure."""
    from .atom_features import atom_features_from_structure
    from .cgcnn_graph import build_radius_cgcnn_graph_from_structure

    atom_feats = atom_features_from_structure(structure, atom_init_path)
    return build_radius_cgcnn_graph_from_structure(
        structure,
        atom_feats,
        radius=graph_radius,
        max_neighbors=max_neighbors,
    )


def metal_features(
    structure: Structure,
    model: object,
    atom_init_path: str,
    *,
    graph_radius: float,
    max_neighbors: int,
) -> np.ndarray:
    """Return the configured CGCNN crystal representation (1-D)."""
    import torch

    graph = _build_graph(
        structure,
        atom_init_path,
        graph_radius=graph_radius,
        max_neighbors=max_neighbors,
    )
    with torch.no_grad():
        representation = model.extract_crystal_repr(graph)
    return representation.numpy().reshape(-1)


def _electronic_character_from_probabilities(
    probabilities: object,
) -> tuple[ElectronicCharacter, float]:
    """Map ``[insulator, metal]`` class probabilities to a prediction."""
    values = np.asarray(probabilities, dtype=float).reshape(-1)
    if values.size != 2:
        raise ValueError(
            f"Metallicity classifier expected 2 class probabilities; got {values.size}."
        )
    predicted_class = int(np.argmax(values))
    character: ElectronicCharacter = "insulator" if predicted_class == 0 else "metal"
    return character, float(values[predicted_class])


def classify_metallicity(
    structure: Structure,
    model: object,
    atom_init_path: str,
    *,
    graph_radius: float,
    max_neighbors: int,
) -> tuple[ElectronicCharacter, float]:
    """Return the CGCNN metallicity prediction and winning class probability.

    The published checkpoint labels class 0 as ``insulator`` and class 1 as
    ``metal``.
    """
    import torch

    graph = _build_graph(
        structure,
        atom_init_path,
        graph_radius=graph_radius,
        max_neighbors=max_neighbors,
    )
    with torch.no_grad():
        probabilities = model(graph)
    return _electronic_character_from_probabilities(probabilities.numpy())
