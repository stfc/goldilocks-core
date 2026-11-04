"""Physics regression suite, v2 shape (v2 epic 9, #9).

These tests used to exercise v1's compute()/legacy_analysis/advice/
parameters.py pipeline -- the acceptance-gate baseline recorded that way
in v2 epic 1 (#2), before v2 had a pipeline of its own to point at.
Epic 8 (#8) reconnected the delivery layers onto service.advise(); this
epic (#9) is where these tests move onto it too, calling the same
analysis/advisors functions the CLI/HTTP/MCP surface now calls, not the
whole-pipeline compute() entry point (deleted alongside the rest of v1's
tree at the end of this epic). Each test's own physical assertion is
unchanged from what it always was -- only the entry point moved.

QE-input-text assertions v1's own versions of these tests made (e.g.
"noncolin = .true." appears in the rendered file) are not repeated here:
that coverage now lives in tests/unit/test_generation_quantum_espresso_
scf.py, which tests the render step directly and in more depth than a
physics-focused test needs to. What belongs here is the *decision*, not
the rendering of it.
"""

from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure
from support import fcc_lead, hcp_gadolinium, magnetic_decision

from goldilocks_core.advisors.convergence import ConvergenceHumanInput, convergence
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.functional import DEFAULT_FUNCTIONAL
from goldilocks_core.advisors.hubbard_u import HubbardUHumanInput, hubbard_u
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigHumanInput,
    magnetic_cell,
)
from goldilocks_core.advisors.nbnd import NbndDecision, nbnd
from goldilocks_core.advisors.occupations import occupations
from goldilocks_core.advisors.pseudo_selection import (
    PseudoRequirements,
    pseudo_requirements,
    select_pseudopotential_table,
)
from goldilocks_core.analysis.composition import composition
from goldilocks_core.analysis.is_magnetic import IsMagneticHumanInput, is_magnetic
from goldilocks_core.analysis.is_metal import IsMetalHumanInput, is_metal
from goldilocks_core.analysis.needs_correlation import needs_correlation
from goldilocks_core.analysis.needs_soc import needs_soc
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.checks import check_all
from goldilocks_core.resolution import FieldState, Provenance, Resolved
from goldilocks_core.service._pseudo import soc_pseudo_table


def _table(
    table_id: str,
    *,
    provider: str = "pseudodojo",
    functional: str = "PBEsol",
    elements: tuple[str, ...] = ("Si",),
) -> PseudoTable:
    return PseudoTable(
        id=table_id,
        provider=provider,
        upstream_table="fixture",
        version="1",
        functional=functional,
        relativistic="scalar",
        accuracy="efficiency",
        licence="fixture licence",
        citation="fixture citation",
        elements=elements,
        asset=AssetSpec(
            f"pseudopotentials/{table_id}",
            "1",
            (AssetFile("pseudopotentials", "source/upf.tgz", "file:///fixture.tgz"),),
        ),
        charge_density_dual=4.0,
    )


def test_elemental_metal_uses_modest_cold_smearing_in_qe_rydberg_units() -> None:
    aluminium = Structure(Lattice.cubic(4.05), ["Al"], [[0.0, 0.0, 0.0]])

    metallicity = is_metal(aluminium)
    decision = occupations(metallicity, magnetic=None)

    # source="heuristic" is v2's replacement for v1's prose "Metallicity
    # was inferred from structure-only heuristics" warning -- the
    # provenance already carries that fact structurally, so no separate
    # warning duplicates it.
    assert metallicity.value == "metal"
    assert metallicity.source == "heuristic"
    assert decision.value.occupations == "smearing"
    assert decision.value.smearing_type == "cold"
    assert decision.value.degauss == 0.01


_SOC_NOTICES = frozenset({"magnetic.soc_suggested", "magnetic.soc_unavailable"})


def _soc_notices(structure: Structure, functional: str) -> dict[str, str]:
    """The spin-orbit notices of ``structure``'s magnetic decision with
    spin-orbit coupling off, given the real registry's verdict on serving
    it under ``functional`` -- code to message."""
    facts = composition(structure)
    magnetism = magnetic_decision(
        structure,
        is_magnetic(structure),
        needs_soc(facts),
        soc_table=soc_pseudo_table(set(facts.value.elements), functional),
    )
    assert magnetism.value.spin_orbit_enabled is False
    return {
        warning.code: warning.message
        for warning in magnetism.value.warnings
        if warning.code in _SOC_NOTICES
    }


def test_heavy_element_prompts_for_soc_without_silently_enabling_it() -> None:
    iodine = Structure(Lattice.cubic(7.0), ["I"], [[0.0, 0.0, 0.0]])

    soc_needed = needs_soc(composition(iodine))
    magnetism = magnetic_decision(
        iodine,
        is_magnetic(iodine),
        soc_needed,
        soc_table=soc_pseudo_table({"I"}, "PBEsol"),
    )
    requirements = pseudo_requirements(
        "PBEsol", spin_orbit_enabled=magnetism.value.spin_orbit_enabled
    )

    assert soc_needed.value is True
    assert magnetism.value.spin_orbit_enabled is False
    assert requirements.relativistic == "scalar"
    assert any(
        warning.code == "magnetic.soc_suggested" for warning in magnetism.value.warnings
    )


def test_soc_is_suggested_with_the_fully_relativistic_table_that_serves_it() -> None:
    """#181: fcc Pb under PBEsol has a fully relativistic PseudoDojo
    table, so the suggestion can be followed and names that table."""
    notices = _soc_notices(fcc_lead(), "PBEsol")

    assert notices.keys() == {"magnetic.soc_suggested"}
    assert notices["magnetic.soc_suggested"].endswith(
        "with it, automatic selection uses the fully relativistic table "
        "pseudodojo-pbesol-efficiency-fr."
    )


def test_soc_is_not_suggested_for_a_lanthanide_no_registered_table_serves() -> None:
    """#181: every lanthanide must use an SSSP table and no SSSP table is
    fully relativistic, so enabling spin_orbit_coupling on hcp Gd makes
    table selection refuse. The notice keeps the caveat and says why
    instead of suggesting a setting the selector refuses."""
    notices = _soc_notices(hcp_gadolinium(), "PBEsol")

    assert notices.keys() == {"magnetic.soc_unavailable"}
    message = notices["magnetic.soc_unavailable"]
    assert message.startswith(
        "heavy, non-s-block elements are present, where spin-orbit coupling "
        "can matter, but spin_orbit_coupling cannot be enabled for them with "
        "this functional and the registered pseudopotential tables: no "
        "pseudopotential table satisfies PBEsol efficiency full for Gd: "
    )
    assert (
        "pseudodojo-pbesol-efficiency-fr: lanthanide and actinide elements "
        "require an SSSP table and missing elements Gd; "
    ) in message
    assert message.endswith(
        "sssp-pbesol-efficiency-sr: relativistic treatment is scalar, requested full"
    )


def test_soc_is_not_suggested_under_a_functional_with_no_relativistic_table() -> None:
    """#181: no fully relativistic LDA table is registered, so Pb under
    LDA gets the unavailable notice, while under PBEsol it gets the
    suggestion."""
    notices = _soc_notices(fcc_lead(), "LDA")

    assert notices.keys() == {"magnetic.soc_unavailable"}
    assert notices["magnetic.soc_unavailable"].endswith(
        "no pseudopotential table satisfies LDA efficiency full for Pb: "
        "pseudodojo-lda-efficiency-sr: relativistic treatment is scalar, "
        "requested full"
    )


def test_explicit_soc_couples_fully_relativistic_pseudos_to_qe_noncollinear_flags() -> (
    None
):
    iodine = Structure(Lattice.cubic(7.0), ["I"], [[0.0, 0.0, 0.0]])

    magnetism = magnetic_decision(
        iodine,
        is_magnetic(iodine),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )
    requirements = pseudo_requirements(
        "PBEsol", spin_orbit_enabled=magnetism.value.spin_orbit_enabled
    )

    assert magnetism.value.spin_orbit_enabled is True
    assert requirements.relativistic == "full"


def test_pseudopotential_functional_must_match_calculation_functional() -> None:
    pbe = _table("pbe-table", functional="PBE")
    pbesol = _table("pbesol-table", functional="PBEsol")
    requirements = PseudoRequirements(
        functional="PBEsol", accuracy="efficiency", relativistic="scalar"
    )

    selected = select_pseudopotential_table(
        {pbe.id: pbe, pbesol.id: pbesol},
        table_id=None,
        elements={"Si"},
        requirements=requirements,
    )

    assert selected.ok
    assert selected.value.id == pbesol.id


def test_lanthanide_element_is_forced_onto_sssp_even_when_pseudodojo_also_matches() -> (
    None
):
    """A1: PseudoDojo's lanthanide table freezes the 4f shell in the core and
    assumes a trivalent ion (wrong for Eu/Yb/Ce) and has no actinide coverage at
    all, so lanthanides/actinides must always be served from SSSP even when a
    PseudoDojo entry would otherwise satisfy every other requirement."""
    pseudodojo = _table("pseudodojo-ce", provider="pseudodojo", elements=("Ce",))
    sssp = _table("sssp-ce", provider="sssp", elements=("Ce",))
    requirements = PseudoRequirements(
        functional="PBEsol", accuracy="efficiency", relativistic="scalar"
    )

    selected = select_pseudopotential_table(
        {pseudodojo.id: pseudodojo, sssp.id: sssp},
        table_id=None,
        elements={"Ce"},
        requirements=requirements,
    )

    assert selected.ok
    assert selected.value.id == sssp.id
    assert selected.value.provider == "sssp"


def test_spin_polarized_structure_gets_a_starting_magnetization() -> None:
    """A2 (stfc/goldilocks-core#177): a spin-polarized structure must not
    reach QE with nspin=2 and no starting_magnetization -- that combination
    relaxes to the non-magnetic solution while the run reports a normal,
    converged SCF. Fixed in v2 epic 5's advisors/magnetic_config.py; this
    test used to stay xfail against v1's own compute() pipeline (never
    fixed there), and now exercises the magnetic decision (magnetic_cell, then
    magnetic_config) directly instead."""
    iron = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])

    magnetism = magnetic_decision(iron, is_magnetic(iron))

    assert magnetism.value.spin_polarized is True
    assert magnetism.value.starting_magnetization
    assert all(
        fraction != 0.0 for fraction in magnetism.value.starting_magnetization.values()
    )


def test_soc_does_not_silently_discard_a_magnetic_structures_magnetism() -> None:
    """A2b (found while hardening physics/ for v2 epic 1): enabling SOC on a
    structure independently advised as magnetic must not silently drop the
    magnetism and emit a non-magnetic noncollinear run. Fixed alongside A2 in
    v2 epic 5's advisors/magnetic_config.py."""
    iron = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])

    magnetism = magnetic_decision(
        iron,
        is_magnetic(iron),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    assert magnetism.value.spin_polarized is True
    assert magnetism.value.spin_orbit_enabled is True
    assert magnetism.value.starting_magnetization


def _electron_count(nelec: float) -> Resolved[ElectronCountDecision]:
    return Resolved(
        ElectronCountDecision(nelec=nelec, tot_charge=0.0),
        Provenance(source="heuristic"),
    )


def test_a_smearing_magnet_has_bands_for_its_seeded_moment() -> None:
    """#131: pw.x holds the moment of a smearing run at 2*nbnd - nelec
    without an error, so a band count without room in the majority channel
    converges to a capped moment: hcp Gd's 22 bands held it at 8.00 uB per
    cell on SCARF, 4.19 eV above the 15.5 uB state 32 bands reached. The
    bands are sized for the moment the starting magnetization seeds."""
    gadolinium = Structure.from_spacegroup(
        "P6_3/mmc", Lattice.hexagonal(3.642, 5.902), ["Gd"], [[1 / 3, 2 / 3, 0.25]]
    )
    nelec = 36.0  # 18-electron Gd pseudopotential, as SSSP's
    magnetism = magnetic_decision(
        gadolinium, is_magnetic(gadolinium), z_valences={"Gd": 18.0}
    )
    scheme = occupations(is_metal(gadolinium), magnetism, _electron_count(nelec))

    bands = nbnd(nelec, scheme, magnetic=magnetism)

    assert scheme.value.occupations == "smearing"
    assert magnetism.value.seeded_moment == pytest.approx(10.0)
    assert 2 * bands.value.nbnd - nelec > magnetism.value.seeded_moment


def test_a_pinned_moment_gets_bands_for_its_majority_channel() -> None:
    """#131: solid O2 (one molecule, 12 electrons) as a non-metal with
    tot_magnetization 2 runs on fixed occupations with 7 spin-up
    electrons. 6 bands made pw.x stop with 'too few spin up bands' after
    check() had passed; the default holds them, and the gate refuses
    fewer."""
    oxygen = Structure(
        Lattice.from_parameters(3.512, 3.512, 4.280, 67.257, 112.743, 115.955),
        ["O", "O"],
        [[0.9105, 0.0895, 0.8544], [0.0895, 0.9105, 0.1456]],
    )
    nelec = 12.0
    magnetism = magnetic_decision(
        oxygen,
        is_magnetic(oxygen),
        z_valences={"O": 6.0},
        human=MagneticConfigHumanInput(tot_magnetization=2.0),
    )
    count = _electron_count(nelec)
    scheme = occupations(
        is_metal(oxygen, IsMetalHumanInput(is_metal="non_metal")), magnetism, count
    )
    bands = nbnd(nelec, scheme, magnetic=magnetism)

    def gate(state: FieldState[NbndDecision]) -> tuple[str, ...]:
        report = check_all(
            occupations=scheme, magnetic=magnetism, electron_count=count, nbnd=state
        )
        return tuple(finding.message for finding in report.blocking)

    assert scheme.value.occupations == "fixed"
    assert scheme.value.tot_magnetization == 2.0
    assert bands.value.nbnd == 7
    assert gate(bands) == ()
    (reason,) = gate(Resolved(NbndDecision(nbnd=6), Provenance(source="human")))
    assert "'too few spin up bands'" in reason


def test_hubbard_u_input_leaves_the_occupation_matrix_free_to_converge() -> None:
    """#127: a +U input must not freeze the Hubbard occupation matrix ns.
    While iter <= mixing_fixed_ns, pw.x resets ns to its iteration-1 value,
    yet it still declares convergence if the density converges inside that
    window (QE 7.3 PW/src/electrons.f90:815-833, mix_rho.f90:162), and the
    freeze restarts at every ionic step (electrons.f90:556). A user's
    nonzero value is kept but flagged, keyed on the Hubbard decision that
    applies the U (#166).

    pw.x reference (SCARF, QE 7.5): the default bundle for this NiO cell
    (MC3D mc3d-29856, U Ni-3d 6.2), run as generated with mixing_fixed_ns = 50
    and again with that line removed. The frozen run converged in 11
    iterations, all 11 printing "RESET ns to initial values"; its total
    energy is 19.7 mRy (0.27 eV) per NiO above the free run's, and its
    pressure is 156.44 kbar against 180.27 kbar. The default LiCoO2 vc-relax
    bundle (mc3d-75346, U Co-3d 3.32) aborted in stres_hub ("non-symmetric
    stress contribution") at its second ionic step.
    """
    nio = Structure(
        Lattice.from_parameters(2.89337, 2.89337, 2.89337, 60, 60, 60),
        ["Ni", "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    hubbard = hubbard_u(nio, needs_correlation(composition(nio)), DEFAULT_FUNCTIONAL)
    assert [(u.element, u.u_ev) for u in hubbard.value.u_values] == [("Ni", 6.2)]

    free = convergence(len(nio), hubbard=hubbard)
    frozen = convergence(
        len(nio), hubbard=hubbard, human=ConvergenceHumanInput(mixing_fixed_ns=50)
    )

    assert free.value.mixing_fixed_ns is None
    assert free.value.warnings == ()
    assert frozen.value.mixing_fixed_ns == 50
    assert [warning.code for warning in frozen.value.warnings] == [
        "convergence.mixing_fixed_ns_freezes_hubbard_occupations"
    ]


def _tenorite_cuo() -> Structure:
    """Tenorite CuO (C2/c, Asbrink & Norrby 1970), its 4-atom primitive
    cell: Cu2+, 3d9."""
    return Structure.from_spacegroup(
        "C2/c",
        Lattice.monoclinic(4.6837, 3.4226, 5.1288, 99.54),
        ["Cu", "O"],
        [[0.25, 0.25, 0.0], [0.0, 0.4184, 0.25]],
    ).get_primitive_structure()


def _la2cuo4() -> Structure:
    """T-type La2CuO4 (Materials Project mp-19735), its 7-atom primitive
    cell: La3+ 4f0, Cu2+ 3d9."""
    return Structure(
        Lattice.from_parameters(3.8138, 3.8138, 7.1412, 105.4875, 105.4875, 90.0),
        ["La", "La", "Cu", "O", "O", "O", "O"],
        [
            [0.360893, 0.360893, 0.721786],
            [0.639107, 0.639107, 0.278214],
            [0.0, 0.0, 0.0],
            [0.0, 0.5, 0.0],
            [0.5, 0.0, 0.0],
            [0.186226, 0.186226, 0.372452],
            [0.813774, 0.813774, 0.627548],
        ],
    )


def _a_type_ce2o3() -> Structure:
    """A-type Ce2O3 (Materials Project mp-2721): Ce3+, 4f1."""
    return Structure.from_spacegroup(
        "P-3m1",
        Lattice.hexagonal(3.89, 6.06),
        ["Ce", "O", "O"],
        [[1 / 3, 2 / 3, 0.2454], [0, 0, 0], [1 / 3, 2 / 3, 0.6471]],
    )


def _layered_licoo2() -> Structure:
    """Layered LiCoO2 (MC3D mc3d-75346), its 4-atom rhombohedral cell:
    low-spin Co3+, 3d6."""
    return Structure(
        Lattice.from_parameters(4.8783, 4.8783, 4.8783, 33.5076, 33.5076, 33.5076),
        ["Li", "Co", "O", "O"],
        [[0.5, 0.5, 0.5], [0.0, 0.0, 0.0], [0.26092] * 3, [0.73908] * 3],
    )


_ML_NON_MAGNETIC = Resolved("non_magnetic", Provenance(source="ml"))
"""What the is_magnetic classifier answered for CuO (0.101), La2CuO4
(0.0055) and LiCoO2 against its 0.324 threshold."""


def _spin_with_u(
    structure: Structure,
    magnetism: FieldState[str],
    *,
    u_by_element: dict[str, float] | None = None,
    spin_polarized: bool | None = None,
):
    hubbard = hubbard_u(
        structure,
        needs_correlation(composition(structure)),
        DEFAULT_FUNCTIONAL,
        HubbardUHumanInput(u_by_element=u_by_element),
    )
    assert hubbard.value.u_values
    return magnetic_cell(
        structure,
        magnetism,
        MagneticConfigHumanInput(spin_polarized=spin_polarized),
        hubbard=hubbard,
    )


@pytest.mark.parametrize(
    ("structure", "magnetism", "u_by_element"),
    [
        (_tenorite_cuo, lambda _s: _ML_NON_MAGNETIC, None),
        (
            _tenorite_cuo,
            lambda s: is_magnetic(s, IsMagneticHumanInput(is_magnetic="non_magnetic")),
            None,
        ),
        (_la2cuo4, lambda _s: _ML_NON_MAGNETIC, {"Cu": 4.0}),
        (_a_type_ce2o3, lambda _s: _ML_NON_MAGNETIC, None),
    ],
    ids=["CuO-ml", "CuO-human-is_magnetic", "La2CuO4-u_by_element", "Ce2O3-ml"],
)
def test_a_hubbard_u_on_an_odd_d_shell_runs_spin_polarized(
    structure, magnetism, u_by_element
) -> None:
    """#147: QE's Dudarev potential is U(1/2 - n_sigma) per spin (QE 7.3
    PW/src/v_of_rho.f90:771-869), and with nspin=1 each spin holds half of
    the occupation matrix (PW/src/new_ns.f90:126). Cu2+ d9 then has 4.5
    electrons per spin, which fill no whole orbital, so +U can neither form
    the moment nor open the gap, and pw.x converges to the wrong state
    without complaint. On SCARF (QE 7.5) the generated nspin=1 CuO deck
    converged to a metal; with nspin=2 it formed 0.66 uB per Cu, 25.6
    meV/atom lower. La2CuO4 with U(Cu) 4.0: a zero-moment metal against
    0.50 uB/cell, 32.5 meV/cell lower. However the classifier was told
    non-magnetic, a U on an odd d or f count (Ce3+ 4f1 too) turns spin
    polarization on."""
    cell = structure()

    state = _spin_with_u(cell, magnetism(cell), u_by_element=u_by_element)

    assert state.value.spin_polarized is True
    assert [warning.code for warning in state.value.warnings] == [
        "magnetic.spin_polarized_for_hubbard_open_shell"
    ]


def test_low_spin_d6_licoo2_with_u_stays_unpolarized() -> None:
    """#147: the rule reads the shell count, not "U implies nspin=2":
    LiCoO2's low-spin Co3+ d6 (U Co 3.32) is non-magnetic, and a
    classifier saying so is kept. (The heuristic tier alone calls any open
    d6 shell magnetic, so the label is the ML tier's.)"""
    state = _spin_with_u(_layered_licoo2(), _ML_NON_MAGNETIC)

    assert state.value.spin_polarized is False
    assert state.value.warnings == ()


def test_an_explicit_spin_polarized_false_keeps_cuo_with_u_unpolarized() -> None:
    state = _spin_with_u(_tenorite_cuo(), _ML_NON_MAGNETIC, spin_polarized=False)

    assert state.value.spin_polarized is False
    assert state.source == "human"
    assert state.value.warnings == ()
