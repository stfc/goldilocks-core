from __future__ import annotations

from pymatgen.core import Lattice, Species, Structure

from goldilocks_core.advisors.electron_count import (
    ElectronCountHumanInput,
    electron_count,
)
from goldilocks_core.advisors.magnetic_config import MagneticCell, OrderingRecord
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable

_IRON_OXIDE = Structure(
    Lattice.cubic(4.0),
    ["Fe", "Fe", "O", "O", "O"],
    [[i / 5, 0, 0] for i in range(5)],
)
_NIO_CELL = Structure(
    Lattice.cubic(4.17), ["Ni", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)
"""A 2-atom NiO cell (CsCl arrangement, not rock salt): the counts below
depend on its atoms and cell sizes only, not on its geometry."""
_IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _metadata(element: str, z_valence: float) -> PseudoMetadata:
    return PseudoMetadata(
        filepath=f"{element}.upf",
        filename=f"{element}.upf",
        header_format="UPF v2",
        element=element,
        z_valence=z_valence,
    )


_NI_O = Resolved(
    (_metadata("Ni", 18.0), _metadata("O", 6.0)), Provenance(source="heuristic")
)


def _cell(
    structure: Structure,
    cell_in_input_basis=_IDENTITY,
    applied: str | None = None,
) -> Resolved[MagneticCell]:
    """The written cell, spin-polarized with the ``applied`` ordering, or
    without spin polarization, which applies none."""
    return Resolved(
        MagneticCell(
            structure=structure,
            spin_polarized=applied is not None,
            spin_orbit_enabled=False,
            magnetic_elements=(),
            ordering=OrderingRecord(
                requested=applied,
                applied=applied,
                criterion="identity" if applied is None else "requested",
            ),
            cell_in_input_basis=cell_in_input_basis,
            tot_magnetization=None,
        ),
        Provenance(source="heuristic"),
    )


def _afm_nio(repeats: tuple[int, int, int]) -> Structure:
    """``_NIO_CELL`` repeated, its two Ni carrying opposite spins."""
    cell = _NIO_CELL * repeats
    spins = iter((5.0, -5.0))
    return Structure(
        cell.lattice,
        [
            Species("Ni", spin=next(spins))
            if site.specie.symbol == "Ni"
            else site.specie
            for site in cell
        ],
        cell.frac_coords,
    )


def test_sums_z_valence_times_atom_count_over_the_whole_structure() -> None:
    pseudos = Resolved(
        (_metadata("Fe", 16.0), _metadata("O", 6.0)), Provenance(source="heuristic")
    )

    state = electron_count(_cell(_IRON_OXIDE), pseudos)

    assert state.ok
    assert state.value.nelec == 2 * 16.0 + 3 * 6.0
    assert state.value.tot_charge == 0.0
    assert state.source == "heuristic"


def test_counts_the_simulated_cell_not_the_uploaded_one() -> None:
    """#128: an applied ordering that doubles NiO's cell doubles its
    electrons; the count follows the cell the writer renders."""
    state = electron_count(
        _cell(_afm_nio((1, 1, 2)), ((1.0, 0, 0), (0, 1.0, 0), (0, 0, 2.0)), "afm"),
        _NI_O,
    )

    assert state.value.nelec == 2 * 18.0 + 2 * 6.0
    assert state.value.tot_charge == 0.0


def test_missing_z_valence_for_a_present_element_blocks() -> None:
    pseudos = Resolved((_metadata("Fe", 16.0),), Provenance(source="heuristic"))

    state = electron_count(_cell(_IRON_OXIDE), pseudos)

    assert not state.ok
    assert state.status == "blocked"
    assert "O" in state.root_cause()


def test_blocked_pseudos_propagates_as_blocked() -> None:
    state = electron_count(
        _cell(_IRON_OXIDE), Blocked(by="pseudopotential selection failed")
    )

    assert not state.ok
    assert state.root_cause() == "pseudopotential selection failed"


def test_unavailable_pseudos_is_treated_as_blocked_not_a_default() -> None:
    state = electron_count(_cell(_IRON_OXIDE), Unavailable(reason="synthetic failure"))

    assert not state.ok
    assert state.status == "blocked"


def test_a_blocked_cell_blocks_the_count() -> None:
    state = electron_count(Blocked(by="unknown site label"), _NI_O)

    assert isinstance(state, Blocked)
    assert state.root_cause() == "unknown site label"


def test_human_nelec_is_the_count_and_its_difference_from_neutral_the_charge() -> None:
    """QE takes a charge, not an electron count (#34): the charge is the
    neutral count of the same cell minus the requested one, decided here
    once (#128) rather than recomputed by the writer."""
    state = electron_count(_cell(_NIO_CELL), _NI_O, ElectronCountHumanInput(nelec=23.0))

    assert state.ok
    assert state.source == "human"
    assert state.value.nelec == 23.0
    assert state.value.tot_charge == 1.0


def test_human_nelec_needs_the_pseudopotentials_for_its_charge() -> None:
    state = electron_count(
        _cell(_NIO_CELL),
        Unavailable(reason="table not installed"),
        ElectronCountHumanInput(nelec=23.0),
    )

    assert isinstance(state, Blocked)
    assert state.root_cause() == "table not installed"


def test_human_nelec_is_refused_when_the_ordering_resized_the_cell() -> None:
    """A nelec counts the uploaded cell's electrons. Once an ordering writes
    a cell of another size it describes a cell the user did not get, and a
    charge derived from it would be the electron difference between the two
    (tot_charge = 24 on NiO's AFM-II cell, #128)."""
    state = electron_count(
        _cell(_afm_nio((1, 1, 2)), ((1.0, 0, 0), (0, 1.0, 0), (0, 0, 2.0)), "afm"),
        _NI_O,
        ElectronCountHumanInput(nelec=24.0),
    )

    assert isinstance(state, Blocked)
    reason = state.root_cause()
    assert "nelec" in reason
    assert "2-atom" in reason
    assert "4-atom" in reason


def test_human_nelec_is_refused_when_enumeration_shrank_a_conventional_cell() -> None:
    """The 8-atom conventional rock-salt cell enumerates to a 4-atom one:
    its cell_in_input_basis is fractional, determinant 1/2."""
    conventional_basis = ((-0.5, -0.5, 0.0), (0.0, 0.5, -0.5), (0.5, -0.5, -1.0))

    state = electron_count(
        _cell(_afm_nio((1, 1, 2)), conventional_basis, "afm"),
        _NI_O,
        ElectronCountHumanInput(nelec=96.0),
    )

    assert isinstance(state, Blocked)
    assert "8-atom" in state.root_cause()
    assert "4-atom" in state.root_cause()


def test_human_nelec_resolves_on_an_ordering_that_keeps_the_cell_size() -> None:
    """An ordering on an uploaded 4-atom cell that writes a 4-atom cell
    with another basis of the same volume leaves the count describing the
    written cell."""
    sheared_same_volume = ((1.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

    state = electron_count(
        _cell(_afm_nio((1, 1, 2)), sheared_same_volume, "afm"),
        _NI_O,
        ElectronCountHumanInput(nelec=47.0),
    )

    assert state.ok
    assert state.value.nelec == 47.0
    assert state.value.tot_charge == 1.0
