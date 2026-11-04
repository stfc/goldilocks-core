from __future__ import annotations

import dataclasses
import re

import pytest
from pydantic import ValidationError
from support import geometry_facts

from goldilocks_core.advisors.boundary import (
    BoundaryHumanInput,
    BoundaryLlmInput,
    boundary,
)
from goldilocks_core.analysis.geometry import SlabGeometry
from goldilocks_core.analysis.symmetry import SymmetryFacts
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable

_DIPOLE = "boundary.dipole_correction_suggested"


def _geometry(dimensionality: str, vacuum_axes: tuple[str, ...] = ()):
    return Resolved(
        geometry_facts(dimensionality, vacuum_axes), Provenance(source="heuristic")
    )


_GROUP_BY_REVERSIBLE_AXES = {
    (): ("P3m1", 156, "trigonal"),
    ("c",): ("P-6m2", 187, "hexagonal"),
    ("a", "b"): ("P2", 3, "monoclinic"),
    ("a", "b", "c"): ("P-1", 2, "triclinic"),
}
"""A space group whose operations reverse exactly these plane normals, for
a cell with a and b perpendicular to c: Janus MoSSe's P3m1 none, the MoS2
sheet's P-6m2 (mirror in the sheet) c's, a two-fold axis along c a's and
b's, and an inversion centre all three."""


def _symmetry(reversible_axes: tuple[str, ...]):
    symbol, number, crystal_system = _GROUP_BY_REVERSIBLE_AXES[reversible_axes]
    facts = SymmetryFacts(
        space_group_symbol=symbol,
        space_group_number=number,
        crystal_system=crystal_system,
        reversible_axes=reversible_axes,
    )
    return Resolved(facts, Provenance(source="heuristic"))


_POLAR = _symmetry(())
"""No operation reverses any plane normal, as in Janus MoSSe (P3m1)."""
_NON_POLAR = _symmetry(("c",))
"""An operation reverses c's plane normal, as the mirror of a MoS2 sheet."""


def _slab(axis: str = "c", **frame: object):
    """A polar-candidate slab: ``geometry_facts``' slab with ``frame`` fields
    replaced (``xy_frame``, ``fits_2d_truncation``, ``vacuum_center``,
    ``vacuum_fraction``)."""
    facts = geometry_facts("2d", (axis,))
    slab = dataclasses.replace(facts.slab, **frame)
    return Resolved(
        dataclasses.replace(facts, slab=slab), Provenance(source="heuristic")
    )


def _sawtooth(message: str) -> tuple[float, float]:
    emaxpos = re.search(r"emaxpos = ([0-9]+(?:\.[0-9]+)?)", message)
    eopreg = re.search(r"eopreg = ([0-9]+(?:\.[0-9]+)?)", message)
    assert emaxpos and eopreg, message
    return float(emaxpos.group(1)), float(eopreg.group(1))


def _in_vacuum(position: float, slab: SlabGeometry) -> bool:
    """Whether a fractional ``position`` along the vacuum axis lies strictly
    inside the vacuum, ``vacuum_center`` +- ``vacuum_fraction`` / 2."""
    offset = abs((position - slab.vacuum_center + 0.5) % 1.0 - 0.5)
    return offset < slab.vacuum_fraction / 2


def test_bulk_3d_is_periodic() -> None:
    state = boundary(_geometry("3d"), _POLAR)

    assert state.ok
    assert state.value.isolation == "periodic"
    assert state.value.warnings == ()


@pytest.mark.parametrize(
    ("dimensionality", "vacuum_axes"),
    [
        ("molecule", ()),
        ("1d", ()),
        ("1d", ("a", "b")),
        ("2d", ("c",)),
        ("molecule", ("a", "b")),
    ],
)
def test_a_cell_periodic_along_any_axis_is_periodic(
    dimensionality: str, vacuum_axes: tuple[str, ...]
) -> None:
    """#126: a molecular crystal (CO2 ranks 'molecule' but fills its cell),
    a wire or a slab is periodic along at least one lattice vector. pw.x has
    no 1D truncation, so a wire stays periodic (#161), and the heuristic
    leaves 2D truncation to an explicit isolation='slab'."""
    state = boundary(_geometry(dimensionality, vacuum_axes), _NON_POLAR)

    assert state.value.isolation == "periodic"
    assert state.source == "heuristic"


@pytest.mark.parametrize("dimensionality", ["molecule", "3d"])
def test_vacuum_along_all_three_axes_is_isolated(dimensionality: str) -> None:
    """A8: a molecule or cluster in a box picks up a spurious interaction
    with its own periodic images. The vacuum decides, not the bond rank: a
    lone atom bonded to its images 5-6 A away ranks '3d'. Martyna-Tuckerman
    removes the images' dipoles too, so a polar molecule gets no notice."""
    state = boundary(_geometry(dimensionality, ("a", "b", "c")), _POLAR)

    assert state.value.isolation == "isolated"
    assert state.source == "heuristic"
    assert state.value.warnings == ()


@pytest.mark.parametrize("dimensionality", ["2d", "molecule", "3d"])
def test_a_cell_without_vacuum_gets_no_dipole_notice(dimensionality: str) -> None:
    """#160: bulk graphite, 2H-MoS2 and Bi2Se3 rank '2d' but have no vacuum,
    and QE allows its dipole correction only in a slab, with the
    discontinuity in the empty space (QE 7.3 PW/Doc/INPUT_PW.def:407-416)."""
    state = boundary(_geometry(dimensionality), _POLAR)

    assert state.value.isolation == "periodic"
    assert state.value.warnings == ()


def test_a_wire_gets_no_dipole_notice() -> None:
    state = boundary(_geometry("1d", ("a", "b")), _POLAR)

    assert state.value.warnings == ()


@pytest.mark.parametrize(
    "reversible_axes", [("c",), ("a", "b", "c")], ids=["mirror", "inversion"]
)
def test_a_slab_whose_normal_some_operation_reverses_gets_no_notice(
    reversible_axes: tuple[str, ...],
) -> None:
    """An inversion centre, a mirror in the sheet, an in-plane C2 axis or an
    S4/S6 axis along the normal cancels the dipole along it, as in all 14
    monolayers of the 2026-10-19 batch."""
    state = boundary(_geometry("2d", ("c",)), _symmetry(reversible_axes))

    assert state.value.isolation == "periodic"
    assert state.value.warnings == ()


def test_a_slab_reversible_only_along_another_axis_is_polar() -> None:
    """Only the vacuum axis's normal matters: reversing a does not cancel a
    dipole along c."""
    state = boundary(_geometry("2d", ("c",)), _symmetry(("a", "b")))

    assert [warning.code for warning in state.value.warnings] == [_DIPOLE]


@pytest.mark.parametrize(
    ("axis", "edir"), [("a", 1), ("b", 2), ("c", 3)], ids=["a", "b", "c"]
)
def test_a_polar_slab_gets_a_dipole_notice_along_its_vacuum_axis(
    axis: str, edir: int
) -> None:
    """QE applies the dipole correction along bg(:, edir), the normal to the
    planes of the other two lattice vectors (QE 7.3
    PW/Doc/INPUT_PW.def:1428-1434), so edir is the vacuum axis. The default
    eamp of 0.001 a.u. would add an external field, so the notice sets it to
    0."""
    state = boundary(_slab(axis), _POLAR)

    assert state.value.isolation == "periodic"
    (warning,) = state.value.warnings
    assert (warning.code, warning.level, warning.category) == (
        _DIPOLE,
        "info",
        "boundary",
    )
    assert f"vacuum axis {axis}" in warning.message
    assert "tefield = .true., dipfield = .true." in warning.message
    assert f"edir = {edir}," in warning.message
    assert "eamp = 0" in warning.message
    assert "not set automatically" in warning.message


@pytest.mark.parametrize(
    ("center", "fraction", "emaxpos", "eopreg"),
    [
        (0.0, 0.8, 0.95, 0.1),
        (0.5, 0.8, 0.45, 0.1),
        (0.3, 0.12, 0.27, 0.06),
        (0.02, 0.6, 0.97, 0.1),
    ],
    ids=["across-the-origin", "mid-cell", "narrow-vacuum", "wrapping"],
)
def test_the_sawtooth_drops_in_the_middle_of_the_vacuum(
    center: float, fraction: float, emaxpos: float, eopreg: float
) -> None:
    """The saw-like potential decreases from emaxpos to emaxpos + eopreg
    (QE 7.3 PW/src/extfield.f90:67-89), and both changes of slope must lie in
    the empty region or unphysical forces result (PW/Doc/INPUT_PW.def:1454-
    1466). The notice centres the drop on the vacuum, over 0.1 of the cell
    (QE's default eopreg) or half the vacuum if that is narrower."""
    geometry = _slab(vacuum_center=center, vacuum_fraction=fraction)

    (warning,) = boundary(geometry, _POLAR).value.warnings

    assert _sawtooth(warning.message) == (emaxpos, eopreg)
    assert _in_vacuum(emaxpos, geometry.value.slab)
    assert _in_vacuum(emaxpos + eopreg, geometry.value.slab)


@pytest.mark.parametrize(
    ("frame", "named"),
    [
        ({"xy_frame": True, "fits_2d_truncation": True}, True),
        ({"xy_frame": False, "fits_2d_truncation": False}, False),
        ({"xy_frame": True, "fits_2d_truncation": False}, False),
    ],
    ids=["room-for-the-2d-truncation", "a-b-out-of-plane", "no-room"],
)
def test_the_notice_offers_the_2d_truncation_only_where_it_fits(
    frame: dict[str, bool], named: bool
) -> None:
    """QE's 2D Coulomb truncation also removes the images' interaction, but
    check_all refuses isolation='slab' unless the slab fits it: a and b in
    the xy plane, c along z (QE 7.3 PW/src/Coul_cut_2D.f90:72-81) and room
    along z (``SlabGeometry.fits_2d_truncation``). The notice names it only
    then."""
    (warning,) = boundary(_slab(**frame), _POLAR).value.warnings

    assert ("isolation='slab'" in warning.message) is named


def test_a_slab_with_vacuum_along_a_is_not_offered_the_2d_truncation() -> None:
    (warning,) = boundary(_slab("a"), _POLAR).value.warnings

    assert "isolation='slab'" not in warning.message


@pytest.mark.parametrize(
    "symmetry",
    [Unavailable(reason="symmetry analysis failed"), Blocked(by="spglib failed")],
    ids=["unavailable", "blocked"],
)
def test_an_unresolved_symmetry_gives_no_notice_and_never_blocks(symmetry) -> None:
    """The notice is advice: without the point group the slab may be
    symmetric, so nothing is said, and the boundary still resolves."""
    state = boundary(_slab(), symmetry)

    assert state.ok
    assert state.value.isolation == "periodic"
    assert state.value.warnings == ()


@pytest.mark.parametrize(
    ("human", "llm"),
    [
        (BoundaryHumanInput(isolation="periodic"), None),
        (None, BoundaryLlmInput(isolation="periodic")),
    ],
    ids=["human", "llm"],
)
def test_an_explicit_isolation_gets_no_dipole_notice(human, llm) -> None:
    state = boundary(_slab(), _POLAR, human=human, llm=llm)

    assert state.value.isolation == "periodic"
    assert state.value.warnings == ()


def test_blocked_geometry_propagates() -> None:
    state = boundary(Blocked(by="synthetic failure"), _POLAR)

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_a_human_slab_wins_over_the_heuristic() -> None:
    """#161: 2D Coulomb truncation is reachable for a slab, by override."""
    state = boundary(
        _geometry("2d", ("c",)), _POLAR, human=BoundaryHumanInput(isolation="slab")
    )

    assert state.value.isolation == "slab"
    assert state.value.warnings == ()
    assert state.source == "human"


def test_an_llm_slab_wins_over_the_heuristic() -> None:
    state = boundary(
        _geometry("2d", ("c",)), _POLAR, llm=BoundaryLlmInput(isolation="slab")
    )

    assert state.value.isolation == "slab"
    assert state.source == "llm"


def test_a_human_value_wins_over_an_llm_value() -> None:
    state = boundary(
        _geometry("molecule", ("a", "b", "c")),
        _NON_POLAR,
        human=BoundaryHumanInput(isolation="periodic"),
        llm=BoundaryLlmInput(isolation="slab"),
    )

    assert state.value.isolation == "periodic"
    assert state.source == "human"


def test_human_override_bypasses_a_blocked_geometry() -> None:
    """Regression for #36 (v2 epic 9, #9): boundary() used to have no
    override path at all, unlike its sibling vdw_method (same epic,
    same GeometryFacts input) -- a Blocked/Unavailable geometry (e.g. a
    disordered structure dimensionality classification can't handle)
    unconditionally blocked the whole run via this one field, with no
    escape hatch, even if the caller supplied every other override."""
    state = boundary(
        Blocked(by="synthetic failure"),
        Unavailable(reason="disordered"),
        human=BoundaryHumanInput(isolation="isolated"),
    )

    assert state.ok
    assert state.value.isolation == "isolated"
    assert state.source == "human"


def test_llm_override_bypasses_a_blocked_geometry_too() -> None:
    state = boundary(
        Blocked(by="synthetic failure"),
        Unavailable(reason="disordered"),
        llm=BoundaryLlmInput(isolation="periodic"),
    )

    assert state.ok
    assert state.value.isolation == "periodic"
    assert state.source == "llm"


@pytest.mark.parametrize("value", ["2D", "none", "martyna-tuckerman"])
def test_quantum_espresso_spellings_are_not_isolation_values(value: str) -> None:
    """The override takes the code-neutral category; the Quantum ESPRESSO
    writer owns the assume_isolated spelling."""
    with pytest.raises(ValidationError, match="'periodic', 'slab' or 'isolated'"):
        BoundaryHumanInput(isolation=value)


def test_the_assume_isolated_field_is_gone() -> None:
    with pytest.raises(ValidationError, match="assume_isolated"):
        BoundaryHumanInput(assume_isolated="none")
