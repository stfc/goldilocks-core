"""Per-atom embedding features for the CGCNN graph.

Looks up each atom's feature vector from an ``atom_init`` JSON (atomic number
-> embedding), as used by the pretrained CGCNN metallicity model.
"""

from __future__ import annotations

import json

from pymatgen.core.structure import Structure


def load_atom_embeddings(atom_init_path: str) -> dict[str, list[float]]:
    """Load the atomic-number -> embedding-vector map from a JSON file."""
    with open(atom_init_path) as handle:
        return json.load(handle)


def atom_features_from_structure(
    structure: Structure,
    atom_init_path: str,
) -> list[list[float]]:
    """Return the embedding vector for each atom in ``structure``.

    Raises:
        ValueError: If the embedding file has no entry for an element.
    """
    embeddings = load_atom_embeddings(atom_init_path)

    features: list[list[float]] = []
    for site in structure:
        number = site.specie.number
        feature = embeddings.get(str(number))
        if feature is None:
            raise ValueError(f"No atom embedding for atomic number {number}.")
        features.append(feature)

    return features
