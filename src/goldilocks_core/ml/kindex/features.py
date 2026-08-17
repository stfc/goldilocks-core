from __future__ import annotations

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import StructureFeatureVector


def extract_c_features(structure: Structure) -> StructureFeatureVector:
    from matminer.featurizers.base import MultipleFeaturizer
    from matminer.featurizers.composition import (
        ElementProperty,
        Stoichiometry,
        ValenceOrbital,
    )

    composition = structure.composition

    featurizer = MultipleFeaturizer(
        [
            ElementProperty.from_preset("magpie", impute_nan=True),
            Stoichiometry(),
            ValenceOrbital(impute_nan=True),
        ]
    )

    feature_names = featurizer.feature_labels()
    values = np.array(featurizer.featurize(composition), dtype=float)

    return StructureFeatureVector(
        values=values,
        feature_names=feature_names,
    )


def extract_s_features(structure: Structure) -> StructureFeatureVector:
    from matminer.featurizers.base import MultipleFeaturizer
    from matminer.featurizers.structure import (
        DensityFeatures,
        GlobalSymmetryFeatures,
    )

    featurizer = MultipleFeaturizer(
        [
            GlobalSymmetryFeatures(),
            DensityFeatures(),
        ]
    )

    raw_feature_names = featurizer.feature_labels()
    raw_values = featurizer.featurize(structure)

    excluded_feature_names = {"crystal_system"}

    filtered_pairs = [
        (name, value)
        for name, value in zip(raw_feature_names, raw_values, strict=True)
        if name not in excluded_feature_names
    ]

    feature_names = [name for name, _ in filtered_pairs]
    values = np.array([value for _, value in filtered_pairs], dtype=float)

    return StructureFeatureVector(
        values=values,
        feature_names=feature_names,
    )


def extract_l_features(structure: Structure) -> StructureFeatureVector:
    lattice = structure.lattice

    feature_names = [
        "a",
        "b",
        "c",
        "alpha",
        "beta",
        "gamma",
        "volume",
    ]

    values = np.array(
        [
            lattice.a,
            lattice.b,
            lattice.c,
            lattice.alpha,
            lattice.beta,
            lattice.gamma,
            lattice.volume,
        ],
        dtype=float,
    )

    return StructureFeatureVector(
        values=values,
        feature_names=feature_names,
    )


def extract_r_features(structure: Structure) -> StructureFeatureVector:
    rec = structure.lattice.reciprocal_lattice

    feature_names = [
        "recip_b1",
        "recip_b2",
        "recip_b3",
        "recip_volume",
        "recip_alpha",
        "recip_beta",
        "recip_gamma",
        "G_tr",
        "G_tr2",
        "G_det",
        "G_cond",
        "bmax_over_bmin",
        "bmid_over_bmin",
        "recip_orthogonality",
    ]

    b1 = rec.a
    b2 = rec.b
    b3 = rec.c
    volume = rec.volume
    alpha = rec.alpha
    beta = rec.beta
    gamma = rec.gamma

    B = np.array(rec.matrix, dtype=float)
    G = B.T @ B

    trG = np.trace(G)
    trG2 = np.trace(G @ G)
    detG = np.linalg.det(G)

    lengths = np.array([b1, b2, b3], dtype=float)
    lengths_sorted = np.sort(lengths)
    bmin, bmid, bmax = lengths_sorted[0], lengths_sorted[1], lengths_sorted[2]

    bmax_over_bmin = bmax / bmin if bmin > 0 else np.nan
    bmid_over_bmin = bmid / bmin if bmin > 0 else np.nan

    cos_alpha = np.cos(np.deg2rad(alpha))
    cos_beta = np.cos(np.deg2rad(beta))
    cos_gamma = np.cos(np.deg2rad(gamma))
    recip_orthogonality = abs(cos_alpha) + abs(cos_beta) + abs(cos_gamma)

    eigenvalues = np.linalg.eigvalsh(G)
    G_cond = eigenvalues.max() / eigenvalues.min() if eigenvalues.min() > 0 else np.nan

    values = np.array(
        [
            b1,
            b2,
            b3,
            volume,
            alpha,
            beta,
            gamma,
            trG,
            trG2,
            detG,
            G_cond,
            bmax_over_bmin,
            bmid_over_bmin,
            recip_orthogonality,
        ],
        dtype=float,
    )

    return StructureFeatureVector(
        values=values,
        feature_names=feature_names,
    )


def extract_cslr_features(structure: Structure) -> StructureFeatureVector:
    c_features = extract_c_features(structure)
    s_features = extract_s_features(structure)
    l_features = extract_l_features(structure)
    r_features = extract_r_features(structure)

    feature_names = (
        c_features.feature_names
        + s_features.feature_names
        + l_features.feature_names
        + r_features.feature_names
    )

    values = np.concatenate(
        [
            c_features.values,
            s_features.values,
            l_features.values,
            r_features.values,
        ]
    )

    return StructureFeatureVector(
        values=values,
        feature_names=feature_names,
    )
