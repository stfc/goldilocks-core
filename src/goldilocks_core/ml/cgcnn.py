"""CGCNN (Crystal Graph Convolutional Neural Network) in PyTorch Geometric.

Ported from the goldilocks k-points models. Used here to load the pretrained
metallicity model and extract a per-crystal representation (the "metal
features" block of the QRF k-distance feature vector). torch / torch_geometric
are heavy optional dependencies imported at module load.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn
from torch.nn import BatchNorm1d, Linear
from torch_geometric.nn import MessagePassing, global_mean_pool


class RBFExpansion(nn.Module):
    """Expand scalar edge distances into Gaussian radial basis features."""

    def __init__(self, vmin: float = 0.0, vmax: float = 8.0, bins: int = 40):
        super().__init__()
        centers = torch.linspace(vmin, vmax, bins)
        self.register_buffer("centers", centers)
        self.gamma = 1 / ((centers[1] - centers[0]).item() ** 2)

    def forward(self, distance: torch.Tensor) -> torch.Tensor:
        return torch.exp(-self.gamma * (distance.unsqueeze(1) - self.centers) ** 2)


class CGCNNConv(MessagePassing):
    """CGCNN gated graph convolution layer."""

    def __init__(self, node_dim: int, edge_dim: int, out_dim: int):
        super().__init__(aggr="add")
        self.lin_f = Linear(2 * node_dim + edge_dim, out_dim)
        self.lin_s = Linear(2 * node_dim + edge_dim, out_dim)
        self.batch_norm = BatchNorm1d(out_dim)

    def forward(self, x, edge_index, edge_attr):
        return self.propagate(edge_index, x=x, edge_attr=edge_attr)

    def message(self, x_i, x_j, edge_attr):
        z = torch.cat([x_i, x_j, edge_attr], dim=1)
        gate = torch.sigmoid(self.lin_f(z))
        msg = F.softplus(self.lin_s(z))
        return gate * msg

    def update(self, aggr_out, x):
        return self.batch_norm(aggr_out + x)


class CGCNN_PyG(nn.Module):
    """CGCNN model. Only the pieces needed to load the checkpoint and extract
    the pooled crystal representation are exercised here; other task heads are
    reconstructed from the checkpoint hyper-parameters so ``load_state_dict``
    matches.
    """

    def __init__(
        self,
        orig_atom_fea_len: int,
        edge_feat_dim: int = 64,
        name: str = "cgcnn",
        h_fea_len: int = 128,
        atom_fea_len: int = 64,
        n_conv: int = 3,
        n_h: int = 3,
        robust_regression: bool = False,
        classification: bool = False,
        quantile_regression: bool = False,
        num_quantiles: int = 1,
        pooling_type: str = "mean_pool",
        num_classes: int = 2,
        additional_compound_features: bool = False,
        add_feat_len: int | None = None,
    ):
        super().__init__()
        self.name = name
        self.classification = classification
        self.robust_regression = robust_regression
        self.quantile_regression = quantile_regression

        if classification:
            self.num_classes = num_classes
        elif quantile_regression:
            self.num_quantiles = num_quantiles

        self.global_pooling = pooling_type
        self.additional_compound_features = additional_compound_features
        if self.additional_compound_features:
            self.add_feat_len = add_feat_len

        self.embedding = nn.Linear(orig_atom_fea_len, atom_fea_len)
        self.rbf = RBFExpansion(vmin=0, vmax=8.0, bins=edge_feat_dim)
        self.convs = nn.ModuleList(
            [
                CGCNNConv(atom_fea_len, edge_feat_dim, out_dim=atom_fea_len)
                for _ in range(n_conv)
            ]
        )
        self.conv_to_fc_softplus = nn.Softplus()

        if self.additional_compound_features:
            self.add_feat_norm = nn.BatchNorm1d(add_feat_len)
            self.proj_add_feat = nn.Linear(add_feat_len, atom_fea_len)
            self.conv_to_fc = nn.Linear(2 * atom_fea_len, h_fea_len)
            self.softplus = nn.Softplus()
        else:
            self.conv_to_fc = nn.Linear(atom_fea_len, h_fea_len)

        if n_h > 1:
            self.fcs = nn.ModuleList(
                [nn.Linear(h_fea_len, h_fea_len) for _ in range(n_h - 1)]
            )
            self.softpluses = nn.ModuleList([nn.Softplus() for _ in range(n_h - 1)])

        if self.classification:
            self.fc_out = nn.Linear(h_fea_len, self.num_classes)
        elif self.robust_regression:
            self.fc_out = nn.Linear(h_fea_len, 2)
        elif self.quantile_regression:
            self.fc_out = nn.Linear(h_fea_len, self.num_quantiles)
        else:
            self.fc_out = nn.Linear(h_fea_len, 1)

    def extract_crystal_repr(self, data) -> torch.Tensor:
        """Return the pooled per-crystal representation [n_graphs, atom_fea_len]."""
        x, edge_index, edge_attr, batch = (
            data.x,
            data.edge_index,
            data.edge_attr,
            data.batch,
        )
        x = self.embedding(x)
        edge_attr = self.rbf(edge_attr.view(-1))
        for conv in self.convs:
            x = conv(x, edge_index, edge_attr)
        if self.global_pooling == "mean_pool":
            x = global_mean_pool(x, batch)
        return x
