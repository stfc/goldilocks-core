from __future__ import annotations

import shutil

import numpy as np
import pytest
from pymatgen.core import Lattice, Species, Structure

from goldilocks_core.advisors import magnetic_config as magnetic_config_module
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigHumanInput,
    magnetic_cell,
)
from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.advisors.magnetic_ordering_ml import (
    MagneticOrderingMlUnavailable,
    OrderingCandidate,
    OrderingMlResult,
)
from goldilocks_core.analysis.is_magnetic import is_magnetic
from goldilocks_core.inputs.structure import StructureInputError
from goldilocks_core.resolution import Provenance, Resolved
from goldilocks_core.service import _magnetic_orderings as magnetic_orderings_module
from goldilocks_core.service._magnetic_orderings import (
    candidate_to_json,
    list_magnetic_orderings,
)

_ROCK_SALT_FEO = Structure(
    Lattice.cubic(4.3), ["Fe", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)

# Mimics a real `enumerate_orderings` candidate: two Fe sites carrying
# opposite `Species.spin`, which the magnetic step splits into two species
# (Fe1/Fe2).
_SPIN_SPLIT_AFM_FEO = Structure(
    Lattice.cubic(4.3),
    [Species("Fe", spin=5.0), Species("Fe", spin=-5.0), "O", "O"],
    [[0.0, 0.0, 0.0], [0.5, 0.5, 0.0], [0.5, 0.0, 0.0], [0.0, 0.5, 0.0]],
)


def test_default_listing_is_unranked_and_never_touches_mmace(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("rank_orderings must not be called unless requested")

    monkeypatch.setattr(magnetic_orderings_module, "rank_orderings", fail)
    # Deterministic regardless of this machine's real PATH (#87): forces
    # AFM enumeration itself unavailable, so the resulting warning is
    # pinned rather than depending on whether enum.x happens to be
    # installed here.
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    report = list_magnetic_orderings(_ROCK_SALT_FEO)

    assert report.ranked is False
    assert [candidate.label for candidate in report.candidates] == ["fm"]
    assert report.candidates[0].energy_per_atom_ev is None
    assert report.candidates[0].is_recommended is False
    [warning] = report.warnings
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "enumlib" in warning.message


def test_ranked_listing_marks_the_lowest_energy_candidate_as_recommended(
    monkeypatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        lambda *_args, **_kwargs: ((_ROCK_SALT_FEO.copy(), "afm"),),
    )

    def fake_rank_orderings(candidates, *, device="cpu"):
        del device
        results = tuple(
            OrderingCandidate(
                label=label,
                structure=structure,
                energy_per_atom_ev=-1.0 if label == "afm-1" else 0.0,
                status="ok",
            )
            for label, structure in candidates
        )
        winner = min(results, key=lambda result: result.energy_per_atom_ev)
        return OrderingMlResult(
            winner=winner, candidates=results, model_id="stub.model"
        )

    monkeypatch.setattr(
        magnetic_orderings_module, "rank_orderings", fake_rank_orderings
    )

    report = list_magnetic_orderings(_ROCK_SALT_FEO, rank_with_mmace=True)

    assert report.ranked is True
    assert report.warnings == ()
    by_label = {candidate.label: candidate for candidate in report.candidates}
    assert by_label["fm"].energy_per_atom_ev == 0.0
    assert by_label["fm"].is_recommended is False
    assert by_label["afm-1"].energy_per_atom_ev == -1.0
    assert by_label["afm-1"].is_recommended is True


def test_every_candidate_is_generated_by_its_label_on_the_listed_structure(
    monkeypatch,
) -> None:
    """#170: a candidate used to carry its own CIF and starting
    magnetizations remapped onto the CIF's labels, seeded at the flat 0.1
    and with symmetry computed on the spin-less CIF, while
    magnetic_ordering=afm seeded the same cell from z_valence. A candidate
    now names itself: run the listed structure with its overrides and the
    one magnetic step writes it, spin-polarized -- the fm candidate too,
    whose label alone used to leave a structure classified non-magnetic
    unpolarized once the Workbench dropped the draft's own spin request."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        lambda *_args, **_kwargs: ((_SPIN_SPLIT_AFM_FEO.copy(), "afm"),),
    )

    report = list_magnetic_orderings(_ROCK_SALT_FEO)

    assert [candidate.label for candidate in report.candidates] == ["fm", "afm-1"]
    for candidate in report.candidates:
        assert candidate.overrides == {"magnetic_ordering": candidate.label}
        assert "structure_content" not in candidate_to_json(candidate)
        assert "structure_format" not in candidate_to_json(candidate)
        cell = magnetic_cell(
            _ROCK_SALT_FEO,
            Resolved("non_magnetic", Provenance(source="ml")),
            MagneticConfigHumanInput(**candidate.overrides),
        ).value
        assert cell.spin_polarized is True, candidate.label
        assert cell.ordering.applied == candidate.label
        assert len(cell.structure) == candidate.natoms


def test_ranking_unavailable_falls_back_to_unranked_with_a_warning(monkeypatch) -> None:
    def fake_rank_orderings(candidates, *, device="cpu"):
        del candidates, device
        raise MagneticOrderingMlUnavailable("set GOLDILOCKS_MACE_BACKBONE ...")

    monkeypatch.setattr(
        magnetic_orderings_module, "rank_orderings", fake_rank_orderings
    )
    # Deterministic regardless of this machine's real PATH (#87) -- see
    # test_default_listing_is_unranked_and_never_touches_mmace above.
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    report = list_magnetic_orderings(_ROCK_SALT_FEO, rank_with_mmace=True)

    assert report.ranked is False
    assert [candidate.label for candidate in report.candidates] == ["fm"]
    codes = {warning.code for warning in report.warnings}
    assert codes == {
        "magnetic.afm_ordering_unavailable",
        "magnetic.ordering_ranking_unavailable",
    }
    ranking_warning = next(
        warning
        for warning in report.warnings
        if warning.code == "magnetic.ordering_ranking_unavailable"
    )
    assert "GOLDILOCKS_MACE_BACKBONE" in ranking_warning.message


def _la2cuo4() -> Structure:
    """T-type La2CuO4 (I4/mmm, Materials Project mp-19735)."""
    return Structure.from_spacegroup(
        "I4/mmm",
        Lattice.tetragonal(3.78, 13.2),
        ["La", "Cu", "O", "O"],
        [[0, 0, 0.3606], [0, 0, 0], [0, 0.5, 0], [0, 0, 0.1828]],
    )


def _fept() -> Structure:
    """L1_0 FePt (P4/mmm, MC3D mc3d-49510)."""
    return Structure.from_spacegroup(
        "P4/mmm",
        Lattice.tetragonal(2.72, 3.71),
        ["Fe", "Pt"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


_SOLID_OXYGEN = Structure(
    Lattice.from_parameters(3.5119, 3.5119, 4.2801, 67.257, 112.743, 115.955),
    ["O", "O"],
    [[0.9105, 0.0895, 0.8544], [0.0895, 0.9105, 0.1456]],
)
"""alpha-O2 (MC3D mc3d-25060): a radical with no local d or f moment."""

_DIAMOND_SILICON = Structure(
    Lattice.from_parameters(3.84, 3.84, 3.84, 60, 60, 60),
    ["Si", "Si"],
    [[0, 0, 0], [0.25, 0.25, 0.25]],
)


def _spins(cell: Structure, element: str) -> set[float]:
    return {
        getattr(site.specie, "spin", None) or 0.0
        for site in cell
        if site.specie.symbol == element
    }


def _never_enumerating(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        lambda *_args, **_kwargs: pytest.fail("enumerated without a sublattice"),
    )


_needs_enumlib = pytest.mark.skipif(
    not enumlib_installed(),
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)


@_needs_enumlib
def test_every_listed_la2cuo4_candidate_compensates_cu_and_leaves_la_unspun() -> None:
    """#143: with 4f0 La3+ seeded too, 5 of 16 listed 'AFM' candidates kept
    both Cu parallel and compensated on La alone."""
    report = list_magnetic_orderings(_la2cuo4())

    afm = [candidate for candidate in report.candidates if candidate.label != "fm"]
    assert afm
    for candidate in afm:
        assert _spins(candidate.structure, "Cu") == {1.0, -1.0}, candidate.label
        assert _spins(candidate.structure, "La") == {0.0}, candidate.label
    assert report.warnings == ()


@_needs_enumlib
def test_no_listed_fept_candidate_is_the_two_site_fe_against_pt_cell() -> None:
    """#143: Fe up / Pt down on the unchanged 2-site cell was listed (and
    applied) as antiferromagnetic; it is ferromagnetic on the Fe sites."""
    report = list_magnetic_orderings(_fept())

    afm = [candidate for candidate in report.candidates if candidate.label != "fm"]
    assert afm
    for candidate in afm:
        assert candidate.natoms >= 4, candidate.label
        assert _spins(candidate.structure, "Fe") == {1.0, -1.0}, candidate.label
        assert _spins(candidate.structure, "Pt") == {0.0}, candidate.label


def test_listing_a_radical_without_moment_bearing_sites_explains_the_fm_only_list(
    monkeypatch,
) -> None:
    """#143: solid O2 is magnetic (a molecular triplet) but has no site to
    order; the listing said nothing about why it held 'fm' alone. The
    warning is the run's, and fits a listing nobody asked an ordering of."""
    _never_enumerating(monkeypatch)

    report = list_magnetic_orderings(_SOLID_OXYGEN)

    assert [candidate.label for candidate in report.candidates] == ["fm"]
    [warning] = report.warnings
    assert warning.code == "magnetic.afm_no_open_shell_sites"
    assert "starting_magnetization per site label" in warning.message
    assert "requested" not in warning.message


def test_listing_undecidable_local_moments_explains_why(monkeypatch) -> None:
    _never_enumerating(monkeypatch)
    uranium_sulfide = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.489), ["U", "S"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )

    report = list_magnetic_orderings(uranium_sulfide)

    assert [candidate.label for candidate in report.candidates] == ["fm"]
    [warning] = report.warnings
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "U (+6)" in warning.message


def test_listing_a_closed_shell_structure_is_fm_alone_without_a_warning(
    monkeypatch,
) -> None:
    """Nothing in diamond Si could order, so 'fm' alone needs no
    explanation -- and enumlib is never asked."""
    _never_enumerating(monkeypatch)

    report = list_magnetic_orderings(_DIAMOND_SILICON)

    assert [candidate.label for candidate in report.candidates] == ["fm"]
    assert report.warnings == ()


def _gdi2_monolayer() -> Structure:
    """A 2H GdI2 sheet like MC2D's monolayer (aedf368b) in the xy plane of a
    cell 19.94 A high along z, 15.98 A of it vacuum."""
    return Structure(
        Lattice.hexagonal(4.357, 19.94),
        ["Gd", "I", "I"],
        [[1 / 3, 2 / 3, 0.0], [2 / 3, 1 / 3, 0.0993], [2 / 3, 1 / 3, -0.0993]],
    )


@_needs_enumlib
def test_a_monolayer_is_listed_with_the_cells_its_labels_write() -> None:
    """#144: the listing and a run keep the same orderings of the
    monolayer, those that keep its vacuum vector c, and number them alike:
    each label writes the listed cell, one sheet with the input's c."""
    gdi2 = _gdi2_monolayer()

    report = list_magnetic_orderings(gdi2)

    afm = [candidate for candidate in report.candidates if candidate.label != "fm"]
    assert [candidate.natoms for candidate in afm] == [6, 12, 12]
    assert report.warnings == ()
    for candidate in afm:
        written = magnetic_cell(
            gdi2, is_magnetic(gdi2), MagneticConfigHumanInput(**candidate.overrides)
        ).value.structure
        assert np.allclose(written.lattice.matrix, candidate.structure.lattice.matrix)
        assert np.array_equal(written.lattice.matrix[2], gdi2.lattice.matrix[2])


def test_a_monolayer_whose_orderings_all_cross_its_vacuum_lists_fm_with_why(
    monkeypatch,
) -> None:
    """#144: a listing of only 'fm' for a magnetic sheet says that every
    ordering found repeats it across its vacuum."""
    gdi2 = _gdi2_monolayer()
    a, b, c = gdi2.lattice.matrix
    doubled = Structure(
        Lattice([a, b, 2 * c]),
        [Species("Gd", spin=5.0), "I", "I", Species("Gd", spin=-5.0), "I", "I"],
        [*gdi2.cart_coords, *(gdi2.cart_coords + c)],
        coords_are_cartesian=True,
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        lambda *_args, **_kwargs: ((doubled, "afm"),),
    )

    report = list_magnetic_orderings(gdi2)

    assert [candidate.label for candidate in report.candidates] == ["fm"]
    [warning] = report.warnings
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "across its vacuum along c" in warning.message


def test_a_disordered_structure_is_refused_before_any_candidate() -> None:
    """#224: a partially occupied site has no species to seed, so the listing
    refuses the structure as advice does, instead of listing a lone 'fm'."""
    wustite_vacancy = Structure(
        Lattice.cubic(4.3), [{"Fe": 0.9}, "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
    )

    with pytest.raises(StructureInputError, match=r"site 1 \(Fe0\.9\)\. Order it"):
        list_magnetic_orderings(wustite_vacancy)
