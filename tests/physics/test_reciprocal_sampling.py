from __future__ import annotations

import math

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.kmesh import k_distance_to_mesh


@pytest.mark.parametrize(
    ("lengths", "spacing"),
    [
        ((3.0, 4.0, 6.0), 0.4),
        ((2.5, 7.0, 11.0), 0.27),
        ((8.0, 8.0, 8.0), 0.15),
    ],
)
def test_mesh_is_minimal_grid_that_bounds_solid_state_reciprocal_spacing(
    lengths: tuple[float, float, float],
    spacing: float,
) -> None:
    """Verify the 2π reciprocal convention against an analytical orthogonal cell."""
    structure = Structure(
        Lattice.orthorhombic(*lengths),
        ["Si"],
        [[0.0, 0.0, 0.0]],
    )

    mesh = k_distance_to_mesh(structure, spacing)
    reciprocal_lengths = tuple(2.0 * math.pi / length for length in lengths)
    expected = tuple(math.ceil(length / spacing) for length in reciprocal_lengths)

    assert mesh == expected
    for reciprocal_length, points in zip(reciprocal_lengths, mesh, strict=True):
        assert reciprocal_length / points <= spacing
        if points > 1:
            assert reciprocal_length / (points - 1) > spacing


def test_vacuum_axis_never_requests_zero_k_points() -> None:
    """A nonperiodic-like long axis remains Gamma-only rather than becoming empty."""
    slab = Structure(
        Lattice.orthorhombic(2.46, 2.46, 40.0),
        ["C", "C"],
        [[0.0, 0.0, 0.5], [0.5, 0.5, 0.5]],
    )

    mesh = k_distance_to_mesh(slab, 0.2)

    assert mesh[:2] == (13, 13)
    assert mesh[2] == 1
