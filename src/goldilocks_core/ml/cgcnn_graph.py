"""Build a PyTorch Geometric graph from a structure for the CGCNN model.

Radius-based neighbor search: nodes are atoms, edges connect atoms within a
cutoff (closest ``max_neighbors``), edge attributes are interatomic distances.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence

import torch
from pymatgen.core.structure import Structure
from torch_geometric.data import Data


def build_radius_cgcnn_graph_from_structure(
    structure: Structure,
    atom_features: Sequence,
    radius: float = 10.0,
    max_neighbors: int = 12,
) -> Data:
    """Return a PyG ``Data`` graph (x, edge_index, edge_attr) for the structure."""
    x = torch.tensor(atom_features, dtype=torch.float32)

    edge_index: list[list[int]] = []
    edge_attr: list[list[float]] = []
    disconnected: list[int] = []

    all_neighbors = structure.get_all_neighbors(radius, include_index=True)
    for i, neighbors in enumerate(all_neighbors):
        neighbors = sorted(neighbors, key=lambda n: n[1])[:max_neighbors]
        if not neighbors:
            disconnected.append(i)
        for neighbor in neighbors:
            edge_index.append([i, neighbor[2]])
            edge_attr.append([neighbor[1]])

    if disconnected:
        warnings.warn(
            f"{len(disconnected)} atoms had no neighbors within radius {radius}: "
            f"{disconnected}",
            stacklevel=2,
        )

    if edge_index:
        edge_index_t = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
        edge_attr_t = torch.tensor(edge_attr, dtype=torch.float32)
    else:
        edge_index_t = torch.empty((2, 0), dtype=torch.long)
        edge_attr_t = torch.empty((0, 1), dtype=torch.float32)

    return Data(x=x, edge_index=edge_index_t, edge_attr=edge_attr_t)
