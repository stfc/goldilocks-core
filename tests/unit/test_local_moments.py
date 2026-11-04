"""local_moments: the one open-shell model behind is_magnetic's heuristic
tier and the antiferromagnetic sublattice (#142).

Structures are real cells built in code (MC3D/MC2D/Materials Project
parameters where the e2e run used them), never one-atom boxes: the radical
rule reads geometry.
"""

from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis.local_moments import local_moments
from goldilocks_core.resolution import Unavailable


def _rock_salt(cation: str, anion: str, a: float) -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, anion], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


def _fluorite(cation: str, a: float) -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, "O"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    )


def _la2cuo4() -> Structure:
    """T-type La2CuO4 (I4/mmm, Materials Project mp-19735)."""
    return Structure.from_spacegroup(
        "I4/mmm",
        Lattice.tetragonal(3.78, 13.2),
        ["La", "Cu", "O", "O"],
        [[0, 0, 0.3606], [0, 0, 0], [0, 0.5, 0], [0, 0, 0.1828]],
    )


def _lanio3() -> Structure:
    """Cubic perovskite LaNiO3."""
    return Structure.from_spacegroup(
        "Pm-3m",
        Lattice.cubic(3.84),
        ["Ni", "La", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0, 0]],
    )


def _ce2o3() -> Structure:
    """A-type Ce2O3 (P-3m1, Materials Project mp-2721)."""
    return Structure.from_spacegroup(
        "P-3m1",
        Lattice.hexagonal(3.89, 6.06),
        ["Ce", "O", "O"],
        [[1 / 3, 2 / 3, 0.2454], [0, 0, 0], [1 / 3, 2 / 3, 0.6471]],
    )


def _lu2o3() -> Structure:
    """Bixbyite Lu2O3 (Ia-3, Materials Project mp-1427)."""
    return Structure.from_spacegroup(
        "Ia-3",
        Lattice.cubic(10.39),
        ["Lu", "Lu", "O"],
        [[0.25, 0.25, 0.25], [-0.0327, 0, 0.25], [0.391, 0.152, 0.380]],
    )


def _feni3() -> Structure:
    """L1_2 FeNi3 (Pm-3m)."""
    return Structure.from_spacegroup(
        "Pm-3m", Lattice.cubic(3.552), ["Fe", "Ni"], [[0, 0, 0], [0, 0.5, 0.5]]
    )


def _gdi2_monolayer() -> Structure:
    """The 2H GdI2 monolayer of MC2D mc2d-aedf368b (P-6m2, 20 A cell)."""
    return Structure(
        Lattice.hexagonal(4.3566, 19.9386),
        ["Gd", "I", "I"],
        [[0, 0, 0.5], [1 / 3, 2 / 3, 0.5993], [1 / 3, 2 / 3, 0.4007]],
    )


def _fe3gete2() -> Structure:
    """Fe3GeTe2 (P6_3/mmc)."""
    return Structure.from_spacegroup(
        "P6_3/mmc",
        Lattice.hexagonal(3.991, 16.33),
        ["Fe", "Fe", "Ge", "Te"],
        [
            [0, 0, 0.1723],
            [1 / 3, 2 / 3, 0.25],
            [2 / 3, 1 / 3, 0.25],
            [1 / 3, 2 / 3, 0.5902],
        ],
    )


def _alpha_uranium() -> Structure:
    """alpha-U (Cmcm, Materials Project mp-44)."""
    return Structure.from_spacegroup(
        "Cmcm", Lattice.orthorhombic(2.854, 5.869, 4.955), ["U"], [[0, 0.1025, 0.25]]
    )


def _solid_oxygen() -> Structure:
    """alpha-O2, MC3D mc3d-25060: O2 molecules 3.3 A apart."""
    return Structure(
        Lattice.from_parameters(3.5119, 3.5119, 4.2801, 67.257, 112.743, 115.955),
        ["O", "O"],
        [[0.9105, 0.0895, 0.8544], [0.0895, 0.9105, 0.1456]],
    )


def _atoms_in_a_box(element: str) -> Structure:
    """The cell of MC3D mc3d-6516 (two C atoms 10.5 A apart, 4.0 uB per cell
    in MC3D), holding two ``element`` atoms."""
    return Structure(
        Lattice.hexagonal(10.56, 17.18),
        [element, element],
        [[1 / 3, 2 / 3, 0.25], [2 / 3, 1 / 3, 0.75]],
    )


def _dimer_in_a_box(element: str, bond: float) -> Structure:
    return Structure(
        Lattice.cubic(10.0),
        [element, element],
        [[0.5, 0.5, 0.5], [0.5, 0.5, 0.5 + bond / 10.0]],
    )


@pytest.mark.parametrize(
    ("structure", "moment_elements"),
    [
        (_la2cuo4(), ("Cu",)),  # La3+ f0, not a group-3 d count; Cu2+ d9
        (_lanio3(), ("Ni",)),  # Ni3+ d7
        (_ce2o3(), ("Ce",)),  # Ce3+ f1
        (_fluorite("Ce", 5.411), ()),  # Ce4+ f0
        (_lu2o3(), ()),  # Lu3+ f14
        (_fluorite("Th", 5.597), ()),  # Th4+ f0
        (_fluorite("U", 5.47), ("U",)),  # U4+ f2
        (_rock_salt("Ni", "O", 4.17), ("Ni",)),  # Ni2+ d8
        (_rock_salt("Zn", "O", 4.28), ()),  # Zn2+ d10
        (  # rutile FeF2: Fe2+ d6
            Structure.from_spacegroup(
                "P4_2/mnm",
                Lattice.tetragonal(4.70, 3.31),
                ["Fe", "F"],
                [[0, 0, 0], [0.30, 0.30, 0]],
            ),
            ("Fe",),
        ),
        (  # zinc-blende ZnSe: Zn2+ d10
            Structure.from_spacegroup(
                "F-43m", Lattice.cubic(5.67), ["Zn", "Se"], [[0, 0, 0], [0.25] * 3]
            ),
            (),
        ),
        (  # cubic CsPbBr3: no d or f shell to open
            Structure.from_spacegroup(
                "Pm-3m",
                Lattice.cubic(5.87),
                ["Cs", "Pb", "Br"],
                [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0]],
            ),
            (),
        ),
    ],
)
def test_the_ionic_rule_counts_d_and_f_electrons_from_the_oxidation_state(
    structure: Structure, moment_elements: tuple[str, ...]
) -> None:
    """With a chalcogen or halogen anion, a cation's shell count fixes its
    moment: f = Z - 54 - ox (lanthanides) or Z - 86 - ox (actinides), d =
    group - ox otherwise, open iff strictly between empty and full."""
    state = local_moments(structure)

    assert state.ok
    assert state.value.rule == "ionic"
    assert state.value.moment_elements == moment_elements
    assert state.value.radical is False
    assert state.source == "heuristic"


def test_shell_counts_report_each_cations_d_or_f_count() -> None:
    """La2CuO4: La3+ is f0 (its f count, not a group-3 d count, although
    pymatgen also calls La a transition metal) and Cu2+ is d9."""
    state = local_moments(_la2cuo4())

    assert state.value.shell_counts == {"La": 0.0, "Cu": 9.0}


def test_a_shell_count_stops_at_a_full_shell() -> None:
    """Calomel's Hg+ is 5d10 6s1: group - ox gives 11, but the d shell holds
    10 and is closed."""
    calomel = Structure.from_spacegroup(
        "I4/mmm",
        Lattice.tetragonal(4.48, 10.91),
        ["Hg", "Cl"],
        [[0, 0, 0.1168], [0, 0, 0.3355]],
    )

    state = local_moments(calomel)

    assert state.value.shell_counts == {"Hg": 10.0}
    assert state.value.moment_elements == ()


def test_a_mixed_valence_count_is_open_and_fractional() -> None:
    """Fe3O4's guess gives Fe +8/3: d 16/3, an open shell. (Spinel in
    pymatgen's origin-choice-1 Fd-3m setting.)"""
    magnetite = Structure.from_spacegroup(
        "Fd-3m",
        Lattice.cubic(8.396),
        ["Fe", "Fe", "O"],
        [[0, 0, 0], [0.625, 0.625, 0.625], [0.3799, 0.3799, 0.3799]],
    )

    state = local_moments(magnetite)

    assert state.value.moment_elements == ("Fe",)
    assert state.value.shell_counts["Fe"] == pytest.approx(16 / 3)


@pytest.mark.parametrize(
    ("structure", "moment_elements"),
    [
        (_gdi2_monolayer(), ("Gd",)),  # +3 only: 4f7
        (_fe3gete2(), ("Fe",)),  # +2 and +3: d6 and d5
    ],
)
def test_without_a_guess_common_states_that_all_leave_an_open_shell_decide(
    structure: Structure, moment_elements: tuple[str, ...]
) -> None:
    """pymatgen guesses no oxidation states for GdI2 or Fe3GeTe2. Every
    common oxidation state of Gd (+3) and of Fe (+2, +3) leaves an open
    shell, so each still carries a moment, and the antiferromagnetic
    sublattice is not refused for the GdI2 monolayer."""
    assert structure.composition.oxi_state_guesses() == ()

    state = local_moments(structure)

    assert state.ok
    assert state.value.rule == "ionic"
    assert state.value.moment_elements == moment_elements
    assert state.value.shell_counts == {}


def test_a_closed_common_state_does_not_decide_without_a_guess() -> None:
    """US is a ferromagnet (Tc 177 K), but pymatgen guesses no oxidation
    states for it and U's one common state (+6) leaves 5f empty. A
    composition the common states cannot charge-balance holds U in some
    other state, so the model cannot tell and says so."""
    uranium_sulfide = _rock_salt("U", "S", 5.489)

    state = local_moments(uranium_sulfide)

    assert isinstance(state, Unavailable)
    assert "U (+6)" in state.reason
    assert "oxidation" in state.reason


def test_common_states_that_disagree_do_not_decide_without_a_guess() -> None:
    """Th3P4-type Ce3Te4 has no guess, and Ce's common states disagree:
    +3 is 4f1, +4 is 4f0."""
    cerium_telluride = Structure.from_spacegroup(
        "I-43d",
        Lattice.cubic(9.54),
        ["Ce", "Te"],
        [[0.375, 0, 0.25], [0.075, 0.075, 0.075]],
    )

    state = local_moments(cerium_telluride)

    assert isinstance(state, Unavailable)
    assert "Ce (+3, +4)" in state.reason


@pytest.mark.parametrize(
    ("structure", "moment_elements"),
    [
        (_feni3(), ("Fe", "Ni")),
        (_rock_salt("Ti", "N", 4.241), ()),  # metallic nitride: not Ti3+ d1
        (_rock_salt("Cr", "N", 4.15), ("Cr",)),
        (_rock_salt("U", "N", 4.877), ("U",)),  # actinide compound
        (_alpha_uranium(), ()),  # elemental actinide metal
        (
            Structure.from_spacegroup(
                "Fm-3m", Lattice.cubic(5.16), ["Ce"], [[0, 0, 0]]
            ),
            ("Ce",),
        ),
        (
            Structure.from_spacegroup(
                "Fm-3m", Lattice.cubic(3.615), ["Cu"], [[0, 0, 0]]
            ),
            (),
        ),
    ],
)
def test_the_metallic_rule_names_the_itinerant_and_4f_moment_carriers(
    structure: Structure, moment_elements: tuple[str, ...]
) -> None:
    """Without a chalcogen or halogen anion (elements, intermetallics,
    nitrides, carbides), Cr-Ni and the open-4f lanthanides carry moments,
    actinides only in a compound; 4d/5d metals, Cu and elemental actinide
    metals do not."""
    state = local_moments(structure)

    assert state.ok
    assert state.value.rule == "metallic"
    assert state.value.moment_elements == moment_elements
    assert state.value.shell_counts == {}


@pytest.mark.parametrize(
    "structure",
    [
        _solid_oxygen(),
        _atoms_in_a_box("C"),
        _atoms_in_a_box("Na"),
        _dimer_in_a_box("O", 1.21),
        _dimer_in_a_box("S", 1.89),
    ],
    ids=["solid-O2", "C-atoms", "Na-atoms", "O2-molecule", "S2-molecule"],
)
def test_isolated_open_shell_atoms_and_o2_s2_molecules_are_radicals(
    structure: Structure,
) -> None:
    """No neighbour within 1.5x the covalent-radius sum: a lone C atom (3P)
    or Na atom (2S), or an O2/S2 molecule (triplet) whose only neighbour is
    its partner."""
    state = local_moments(structure)

    assert state.ok
    assert state.value.radical is True
    assert state.value.moment_elements == ()


@pytest.mark.parametrize(
    "structure",
    [
        _rock_salt("Na", "Cl", 5.640),
        Structure.from_spacegroup("Im-3m", Lattice.cubic(4.235), ["Na"], [[0, 0, 0]]),
        _rock_salt("Li", "H", 4.083),
        _dimer_in_a_box("N", 1.10),
        Structure.from_spacegroup("Fm-3m", Lattice.cubic(5.26), ["Ar"], [[0, 0, 0]]),
        Structure.from_spacegroup(  # CaC2-type BaO2
            "I4/mmm",
            Lattice.tetragonal(3.81, 6.77),
            ["Ba", "O"],
            [[0, 0, 0], [0, 0, 0.39]],
        ),
    ],
    ids=["NaCl", "bcc-Na", "LiH", "N2-molecule", "solid-Ar", "BaO2-peroxide"],
)
def test_bonded_atoms_and_closed_shells_are_not_radicals(
    structure: Structure,
) -> None:
    """NaCl, bcc Na and LiH sit at 1.05, 1.09 and 1.25 times their
    covalent-radius sums, inside the 1.5x cutoff. N2 is a closed-shell
    dimer, solid Ar's atoms are closed shells however far apart (1.75x),
    and a peroxide's O2 unit is bonded to its cations."""
    state = local_moments(structure)

    assert state.ok
    assert state.value.radical is False


def test_an_element_without_a_covalent_radius_leaves_the_radical_test_unavailable() -> (
    None
):
    """pymatgen tabulates covalent radii up to Cm, so whether a Cl next to
    Cf is isolated cannot be tested."""
    californium_chloride = Structure.from_spacegroup(
        "P6_3/m",
        Lattice.hexagonal(7.39, 4.09),
        ["Cf", "Cl"],
        [[1 / 3, 2 / 3, 0.25], [0.385, 0.301, 0.25]],
    )

    state = local_moments(californium_chloride)

    assert isinstance(state, Unavailable)
    assert "Cf" in state.reason
