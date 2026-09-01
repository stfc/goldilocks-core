from __future__ import annotations

import json

from pymatgen.core.structure import Structure


def load_atom_embeddings(atom_init_path: str) -> dict[str, list[float]]:
    with open(atom_init_path) as handle:
        return json.load(handle)


def atom_features_from_structure(
    structure: Structure,
    atom_init_path: str,
) -> list[list[float]]:
    embeddings = load_atom_embeddings(atom_init_path)

    features: list[list[float]] = []
    for site in structure:
        number = site.specie.number
        feature = embeddings.get(str(number))
        if feature is None:
            raise ValueError(f"No atom embedding for atomic number {number}.")
        features.append(feature)

    return features
