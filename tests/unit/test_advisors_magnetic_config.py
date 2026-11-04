from __future__ import annotations

import math
import shutil

import numpy as np
import pytest
from numpy.linalg import LinAlgError
from pydantic import ValidationError
from pymatgen.core import Lattice, Species, Structure
from pymatgen.electronic_structure.core import Magmom
from support import magnetic_decision, molybdenum_disulfide_monolayer

from goldilocks_core.advisors import magnetic_config as magnetic_config_module
from goldilocks_core.advisors.functional import DEFAULT_FUNCTIONAL
from goldilocks_core.advisors.hubbard_u import (
    HubbardUDecision,
    HubbardUHumanInput,
    hubbard_u,
)
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigHumanInput,
    MagneticConfigLlmInput,
    MomentDirection,
    OrderingRecord,
    enumerate_magnetic_orderings,
    framed_cell,
    magnetic_cell,
    magnetic_config,
)
from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.analysis.geometry import slab_geometry, slab_layers, vacuum_axes
from goldilocks_core.analysis.is_magnetic import is_magnetic
from goldilocks_core.analysis.local_moments import local_moments
from goldilocks_core.analysis.symmetry import symmetry
from goldilocks_core.assets.pseudopotentials.registry import load_tables
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable

_IRON = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])
_SILICON = Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])
_ROCK_SALT_FEO = Structure(
    Lattice.cubic(4.3), ["Fe", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)
_BCC_IRON = Structure(Lattice.cubic(2.87), ["Fe", "Fe"], [[0, 0, 0], [0.5, 0.5, 0.5]])
_DIAMOND_SILICON = Structure(
    Lattice.from_parameters(3.84, 3.84, 3.84, 60, 60, 60),
    ["Si", "Si"],
    [[0, 0, 0], [0.25, 0.25, 0.25]],
)

_ENUMLIB_MISSING = not enumlib_installed()


def _on_path(*names: str):
    """A ``shutil.which`` that finds exactly ``names``."""
    return lambda name: f"/usr/bin/{name}" if name in names else None


def _enumerating(*orderings: tuple[Structure, str]):
    """An ``enumerate_orderings`` stub returning ``(structure, origin)``
    pairs -- the worker process is out of reach of a monkeypatch."""
    return lambda *_args, **_kwargs: orderings


def _failing_with(error: BaseException):
    def enumerate_orderings(*_args, **_kwargs):
        raise error

    return enumerate_orderings


def test_magnetic_structure_gets_spin_polarized_and_a_starting_magnetization() -> None:
    """A2 (stfc/goldilocks-core#177): spin_polarized=True must always come
    with a non-empty, non-zero starting_magnetization -- never implicit
    zero moments that relax to the non-magnetic solution. Without a
    z_valences (no pseudopotential chosen yet), every element gets
    aiida-quantumespresso's own flat default (0.1), not a guessed
    calibrated value."""
    state = magnetic_decision(_IRON, is_magnetic(_IRON))

    assert state.ok
    assert state.value.spin_polarized is True
    assert state.value.magnetic_elements == ("Fe",)
    assert state.value.starting_magnetization == {"Fe": 0.1}


def test_starting_magnetization_uses_moment_target_when_z_valence_known() -> None:
    """Once a pseudopotential's z_valence is known, the fraction is
    aiida-quantumespresso's own target_moment / z_valence -- Fe's target is
    5 Bohr magnetons (magnetization.yaml), so a Fe pseudopotential with
    z_valence=16 gives 5/16, not the flat default."""
    state = magnetic_decision(_IRON, is_magnetic(_IRON), z_valences={"Fe": 16.0})

    assert state.value.starting_magnetization == {"Fe": 5.0 / 16.0}


_HCP_GADOLINIUM = Structure.from_spacegroup(
    "P6_3/mmc", Lattice.hexagonal(3.642, 5.902), ["Gd"], [[1 / 3, 2 / 3, 0.25]]
)


def test_the_seeded_moment_is_the_net_moment_the_seeds_start_from() -> None:
    """#131: ``seeded_moment`` converts the seeds back to Bohr magnetons
    with the same z_valences, summed over sites: hcp Gd's two sites at
    5/18 of 18 electrons start from 10 uB per cell."""
    state = magnetic_decision(
        _HCP_GADOLINIUM, is_magnetic(_HCP_GADOLINIUM), z_valences={"Gd": 18.0}
    )

    assert state.value.starting_magnetization == {"Gd": 5.0 / 18.0}
    assert state.value.seeded_moment == pytest.approx(10.0)


def test_the_ferromagnetic_seeded_moment_counts_every_species() -> None:
    """aiida's +0.1 on species without a moment target is part of the
    seed: rock-salt FeO starts from Fe's 5 uB plus O's 0.1 x 6."""
    state = magnetic_decision(
        _ROCK_SALT_FEO, is_magnetic(_ROCK_SALT_FEO), z_valences={"Fe": 16.0, "O": 6.0}
    )

    assert state.value.seeded_moment == pytest.approx(5.6)


def test_the_seeded_moment_needs_every_element_s_z_valence() -> None:
    """Without a z_valence for an element its seed has no size in Bohr
    magnetons (the flat 0.1 fraction applies to any valence), so the
    moment is unknown rather than guessed."""
    without = magnetic_decision(_ROCK_SALT_FEO, is_magnetic(_ROCK_SALT_FEO))
    partial = magnetic_decision(
        _ROCK_SALT_FEO, is_magnetic(_ROCK_SALT_FEO), z_valences={"Fe": 16.0}
    )

    assert without.value.spin_polarized and partial.value.spin_polarized
    assert without.value.seeded_moment is None
    assert partial.value.seeded_moment is None


def test_a_human_starting_magnetization_seeds_its_own_moment() -> None:
    """A human fraction is scaled by the same z_valence; a label left out
    keeps its computed seed (#185), so one bcc Fe site at 0.5 of 16
    electrons and the other at 5/16 seed 8 + 5 uB, and opposite fractions
    cancel."""
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )
    one_site = MagneticConfigHumanInput(starting_magnetization={"Fe0": 0.5})
    opposite = MagneticConfigHumanInput(
        starting_magnetization={"Fe0": 0.5, "Fe1": -0.5}
    )

    seeded = magnetic_decision(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        z_valences={"Fe": 16.0},
        human=one_site,
    )
    cancelled = magnetic_decision(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        z_valences={"Fe": 16.0},
        human=opposite,
    )

    assert seeded.value.seeded_moment == pytest.approx(13.0)
    assert cancelled.value.seeded_moment == pytest.approx(0.0)


def test_a_run_without_spin_polarization_seeds_no_moment() -> None:
    state = magnetic_decision(
        _DIAMOND_SILICON, is_magnetic(_DIAMOND_SILICON), z_valences={"Si": 4.0}
    )

    assert not state.value.spin_polarized
    assert state.value.seeded_moment is None


def test_starting_magnetization_is_keyed_by_the_cell_s_species_labels() -> None:
    """Regression for #32 (v2 epic 9, #9): a real structure's per-site
    labels are not always identical to its element symbols -- pymatgen's
    own CIF writer/reader already assigns distinct labels like
    'Fe0'/'Fe1' by default, not just AFM-relabeled structures. Before the
    fix, this heuristic default was keyed by element symbol
    (composition(structure).value.elements), which no longer matched
    generation/quantum_espresso/scf.py's label-keyed species_index once
    #27 made that label-keyed -- a bare KeyError on every bundled example
    structure. The seeds are keyed by the cell's species labels: two
    same-element, same-spin sites are one species, whatever labels the
    upload gave them (#170)."""
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )

    state = magnetic_decision(two_iron_sites, is_magnetic(two_iron_sites))

    assert state.ok
    assert [site.label for site in state.value.cell] == ["Fe", "Fe"]
    assert state.value.starting_magnetization == {"Fe": 0.1}


def test_an_element_key_on_labelled_sites_seeds_them_as_one_species() -> None:
    """#46 refused {"Fe": 0.5} on pymatgen's Fe0/Fe1 labels rather than
    let it seed nothing (it used to crash in generation with a KeyError).
    An element symbol now sets all of that element's sites (#185): both
    Fe start at 0.5, one species."""
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )

    state = magnetic_decision(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        human=MagneticConfigHumanInput(starting_magnetization={"Fe": 0.5}),
    )

    assert [site.label for site in state.value.cell] == ["Fe", "Fe"]
    assert state.value.starting_magnetization == {"Fe": 0.5}
    assert state.value.human_seeded_labels == ("Fe",)


def test_starting_magnetization_override_with_real_labels_is_accepted() -> None:
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )

    state = magnetic_decision(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        human=MagneticConfigHumanInput(
            starting_magnetization={"Fe0": 0.5, "Fe1": -0.5}
        ),
    )

    assert state.ok
    assert state.value.starting_magnetization == {"Fe1": 0.5, "Fe2": -0.5}


def test_starting_magnetization_covers_every_element_not_just_magnetic_candidates() -> (
    None
):
    """Matches aiida-quantumespresso's own behaviour: every kind gets an
    entry once spin-polarized, including non-magnetic-candidate species like
    O, so no single species sits at exactly zero and re-locks the spin
    symmetry the rest of the structure is trying to break."""
    iron_oxide = Structure(
        Lattice.cubic(4.0),
        ["Fe", "Fe", "O", "O", "O"],
        [[i / 5, 0, 0] for i in range(5)],
    )

    state = magnetic_decision(iron_oxide, is_magnetic(iron_oxide))

    assert state.value.starting_magnetization == {"Fe": 0.1, "O": 0.1}


def test_unlisted_element_falls_back_to_the_flat_default_even_with_z_valence() -> None:
    """Cu has a filled d-shell as a neutral element and has no target in
    aiida's table -- it must not be scaled, even if a z_valence is
    supplied for it."""
    copper = Structure(Lattice.cubic(3.6), ["Cu"], [[0.0, 0.0, 0.0]])

    state = magnetic_decision(
        copper,
        Resolved("magnetic", Provenance(source="heuristic")),
        z_valences={"Cu": 11.0},
    )

    assert state.value.starting_magnetization == {"Cu": 0.1}


def test_non_magnetic_structure_has_no_starting_magnetization() -> None:
    state = magnetic_decision(_SILICON, is_magnetic(_SILICON))

    assert state.value.spin_polarized is False
    assert state.value.starting_magnetization is None
    assert state.value.magnetic_elements == ()


def test_unavailable_magnetism_defaults_to_spin_polarized_with_a_warning() -> None:
    """Unavailable (the heuristic tried and could not tell) is not the same
    as Blocked (nothing upstream could even attempt an answer) -- there is
    still a safe default: spin-polarized, because the SCF can quench a
    seeded moment but nspin=1 can never find one (#142)."""
    state = magnetic_decision(
        _BCC_IRON, Unavailable(reason="no oxidation-state guess for Fe")
    )

    assert state.ok
    assert state.value.spin_polarized is True
    assert state.value.starting_magnetization == {"Fe": 0.1}
    assert state.source == "heuristic"
    (warning,) = state.value.warnings
    assert warning.code == "magnetic.magnetism_unknown_defaulted_spin_polarized"
    assert warning.level == "warning"
    assert "no oxidation-state guess for Fe" in warning.message
    assert "spin_polarized" in warning.message


def test_blocked_magnetism_propagates_as_blocked() -> None:
    state = magnetic_cell(_IRON, Blocked(by="synthetic failure"))

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_human_can_force_spin_polarization_on() -> None:
    state = magnetic_cell(
        _SILICON,
        is_magnetic(_SILICON),
        human=MagneticConfigHumanInput(spin_polarized=True),
    )

    assert state.value.spin_polarized is True
    assert state.source == "human"


def test_tot_magnetization_alone_implies_spin_polarized() -> None:
    """Regression for #34 (v2 epic 9, #9): a human-supplied
    tot_magnetization (or starting_magnetization) with no spin_polarized
    override at all is an unambiguous request for a spin-polarized
    calculation -- before this, it was silently dropped whenever
    spin_polarized otherwise resolved False (e.g. a non-magnetic
    structure's heuristic default)."""
    state = magnetic_decision(
        _SILICON,
        is_magnetic(_SILICON),
        human=MagneticConfigHumanInput(tot_magnetization=2.0),
    )

    assert state.ok
    assert state.value.spin_polarized is True
    assert state.source == "human"
    assert state.value.tot_magnetization == 2.0


@pytest.mark.parametrize(
    ("spin_orbit_coupling", "spin_mode"), [(False, "none"), (True, "noncollinear")]
)
def test_explicit_spin_polarized_false_drops_a_tot_magnetization_and_warns(
    spin_orbit_coupling: bool, spin_mode: str
) -> None:
    """An explicit spin_polarized=False is a human override too and must
    win outright over a simultaneously-given tot_magnetization -- but
    silently dropping the latter with zero signal is still wrong, so
    this warns instead. The ignored value is dropped from the decision,
    with or without spin-orbit coupling, so it never reaches the writer
    (#146: pw.x refuses tot_magnetization without nspin=2)."""
    state = magnetic_decision(
        _DIAMOND_SILICON,
        is_magnetic(_DIAMOND_SILICON),
        human=MagneticConfigHumanInput(
            spin_polarized=False,
            tot_magnetization=2.0,
            spin_orbit_coupling=spin_orbit_coupling,
        ),
    )

    assert state.ok
    assert state.value.spin_polarized is False
    assert state.value.tot_magnetization is None
    assert state.value.spin_mode == spin_mode
    assert any(
        warning.code == "magnetic.magnetization_ignored_spin_polarized_false"
        for warning in state.value.warnings
    )


def test_spin_orbit_coupling_refuses_a_tot_magnetization() -> None:
    """#146: spin-orbit coupling makes the run noncollinear (pw.x sets
    nspin=4, QE 7.3 PW/src/input.f90:718), and pw.x accepts
    tot_magnetization only with nspin=2 (input.f90:761-762). The request
    is refused here, where /explain shows it, instead of passing the gate
    and failing in the writer."""
    state = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True, tot_magnetization=2.0),
    )

    assert isinstance(state, Blocked)
    assert "tot_magnetization" in state.root_cause()
    assert "spin_orbit_coupling" in state.root_cause()
    assert "starting_magnetization" in state.root_cause()


@pytest.mark.parametrize(
    ("structure", "spin_orbit_coupling", "spin_mode"),
    [
        (_DIAMOND_SILICON, False, "none"),
        (_BCC_IRON, False, "collinear"),
        (_BCC_IRON, True, "noncollinear"),
        (_DIAMOND_SILICON, True, "noncollinear"),
    ],
)
def test_spin_mode_is_noncollinear_with_spin_orbit_otherwise_follows_spin(
    structure: Structure, spin_orbit_coupling: bool, spin_mode: str
) -> None:
    """The one spin treatment the gate, the occupations advisor, the
    writer and the job's layout read (#146): spin-orbit coupling is
    noncollinear whether or not the run is magnetic."""
    state = magnetic_decision(
        structure,
        is_magnetic(structure),
        human=MagneticConfigHumanInput(spin_orbit_coupling=spin_orbit_coupling),
    )

    assert state.value.spin_mode == spin_mode


def test_giving_both_tot_and_starting_magnetization_does_not_error() -> None:
    """goldilocks-qe-pw-parameter-audit.md P0 finding #2: QE's own source
    (input.f90) does not error on this combination -- the design doc had
    briefly asserted it was a hard mutual exclusion elsewhere in itself and
    self-corrected. Both pass through unchanged."""
    state = magnetic_decision(
        _IRON,
        is_magnetic(_IRON),
        human=MagneticConfigHumanInput(
            tot_magnetization=2.0, starting_magnetization={"Fe": 0.7}
        ),
    )

    assert state.ok
    assert state.value.tot_magnetization == 2.0
    assert state.value.starting_magnetization == {"Fe": 0.7}


def test_soc_enabled_on_a_magnetic_structure_keeps_the_magnetism() -> None:
    """A2b: enabling SOC must not silently discard magnetism -- both
    starting_magnetization and the angle1/angle2 direction QE's
    noncollinear mode needs must be present together."""
    state = magnetic_decision(
        _IRON,
        is_magnetic(_IRON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    assert state.value.spin_polarized is True
    assert state.value.spin_orbit_enabled is True
    assert state.value.starting_magnetization == {"Fe": 0.1}
    assert state.value.angle1 == {"Fe": 0.0}
    assert state.value.angle2 == {"Fe": 0.0}


def test_soc_enabled_on_a_non_magnetic_structure_has_no_angles() -> None:
    """SOC without magnetism is only correct when the structure genuinely
    is non-magnetic -- confirmed by there being no is_magnetic override
    forcing it on here."""
    state = magnetic_decision(
        _SILICON,
        is_magnetic(_SILICON),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    assert state.value.spin_polarized is False
    assert state.value.spin_orbit_enabled is True
    assert state.value.angle1 is None
    assert state.value.angle2 is None


_NEEDS_SOC = Resolved(True, Provenance(source="heuristic"))
_FR_TABLE = Resolved(
    load_tables()["pseudodojo-pbesol-efficiency-fr"], Provenance(source="heuristic")
)
_NO_FR_TABLE = Unavailable(reason="no pseudopotential table satisfies the request")


def _soc_codes(state) -> set[str]:
    return {
        warning.code
        for warning in state.value.warnings
        if warning.code in {"magnetic.soc_suggested", "magnetic.soc_unavailable"}
    }


def test_soc_is_never_auto_enabled_even_when_needs_soc_says_yes() -> None:
    state = magnetic_decision(
        _BCC_IRON, is_magnetic(_BCC_IRON), needs_soc=_NEEDS_SOC, soc_table=_FR_TABLE
    )

    assert state.value.spin_orbit_enabled is False
    (notice,) = (
        warning
        for warning in state.value.warnings
        if warning.code == "magnetic.soc_suggested"
    )
    assert (notice.level, notice.category) == ("info", "magnetic")
    assert notice.message == (
        "heavy, non-s-block elements are present; consider enabling "
        "spin_orbit_coupling (not enabled automatically -- it changes cost and "
        "setup); with it, automatic selection uses the fully relativistic table "
        "pseudodojo-pbesol-efficiency-fr."
    )


def test_soc_no_table_can_serve_is_reported_unavailable_with_the_reason() -> None:
    """#181: a suggestion the table selector would refuse is replaced by
    ``magnetic.soc_unavailable``, which keeps the caveat and carries the
    selector's refusal."""
    state = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        needs_soc=_NEEDS_SOC,
        soc_table=_NO_FR_TABLE,
    )

    (notice,) = (
        warning
        for warning in state.value.warnings
        if warning.code in {"magnetic.soc_suggested", "magnetic.soc_unavailable"}
    )
    assert (notice.code, notice.level, notice.category) == (
        "magnetic.soc_unavailable",
        "info",
        "magnetic",
    )
    assert notice.message == (
        "heavy, non-s-block elements are present, where spin-orbit coupling can "
        "matter, but spin_orbit_coupling cannot be enabled for them with this "
        "functional and the registered pseudopotential tables: no "
        "pseudopotential table satisfies the request"
    )


@pytest.mark.parametrize("soc_table", [_FR_TABLE, _NO_FR_TABLE, None])
def test_no_soc_notice_once_spin_orbit_coupling_is_on(soc_table) -> None:
    state = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        needs_soc=_NEEDS_SOC,
        soc_table=soc_table,
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    assert state.value.spin_orbit_enabled is True
    assert _soc_codes(state) == set()


@pytest.mark.parametrize("soc_table", [_FR_TABLE, _NO_FR_TABLE])
def test_no_soc_notice_when_needs_soc_is_false(soc_table) -> None:
    state = magnetic_decision(
        _BCC_IRON,
        is_magnetic(_BCC_IRON),
        needs_soc=Resolved(False, Provenance(source="heuristic")),
        soc_table=soc_table,
    )

    assert _soc_codes(state) == set()


def test_no_soc_notice_without_a_table_verdict() -> None:
    """No verdict on serving spin-orbit coupling, no SOC notice: the notice
    never recommends a setting the table selector was not asked about."""
    state = magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON), needs_soc=_NEEDS_SOC)

    assert _soc_codes(state) == set()


_HCP_COBALT = Structure.from_spacegroup(
    "P6_3/mmc", Lattice.hexagonal(2.507, 4.070), ["Co"], [[1 / 3, 2 / 3, 0.25]]
)


def _codes(state) -> set[str]:
    return {warning.code for warning in state.value.warnings}


def test_a_moment_direction_is_a_lattice_direction_of_the_uploaded_cell() -> None:
    """#172: moment_direction is a direction [uvw] of the uploaded cell,
    written as QE's angle1 (from Cartesian z) and angle2 (from x, in the
    xy plane) for every species. In pymatgen's hcp setting b + c is
    (-a/2, a*sqrt(3)/2, c): angle1 = atan(a/c), angle2 = 120 degrees. The
    old hard-wired angle1 = angle2 = 0 put every moment along +z."""
    state = magnetic_decision(
        _HCP_COBALT,
        is_magnetic(_HCP_COBALT),
        human=MagneticConfigHumanInput(
            spin_orbit_coupling=True, moment_direction=(0, 1, 1)
        ),
    )

    facts = state.value
    assert facts.moment_direction == MomentDirection(
        uvw=(0.0, 1.0, 1.0), source="human"
    )
    assert facts.angle1 == pytest.approx({"Co": math.degrees(math.atan2(2.507, 4.070))})
    assert facts.angle2 == pytest.approx({"Co": 120.0})
    assert "magnetic.soc_moment_direction_defaulted" not in _codes(state)


def test_the_default_moment_direction_is_the_uploaded_cell_s_c_axis() -> None:
    """#172: without moment_direction, a magnetic spin-orbit run starts its
    moments along [001] of the uploaded cell -- a crystal direction, so it
    keeps its meaning however the cell is oriented -- with an info notice
    that the direction is a physical choice. This FePt cell has c along
    +y, so the moments are written at angle1 = angle2 = 90 degrees, not
    along Cartesian +z (QE's own default, which was hard-wired)."""
    a, c = 2.729, 3.71
    fept = Structure(
        Lattice([[a, 0, 0], [0, 0, -a], [0, c, 0]]),
        ["Fe", "Pt"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )

    state = magnetic_decision(
        fept,
        is_magnetic(fept),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    facts = state.value
    assert facts.moment_direction == MomentDirection(
        uvw=(0.0, 0.0, 1.0), source="heuristic"
    )
    assert facts.angle1 == {"Fe": 90.0, "Pt": 90.0}
    assert facts.angle2 == {"Fe": 90.0, "Pt": 90.0}
    (notice,) = (
        warning
        for warning in facts.warnings
        if warning.code == "magnetic.soc_moment_direction_defaulted"
    )
    assert notice.level == "info"
    assert "[0 0 1]" in notice.message
    assert "moment_direction" in notice.message


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"spin_orbit_coupling": True, "spin_polarized": False},
    ],
    ids=["collinear", "spin-orbit-non-magnetic"],
)
def test_a_moment_direction_without_magnetic_spin_orbit_coupling_is_ignored(
    settings: dict[str, object],
) -> None:
    """#172: only a magnetic noncollinear run has a moment direction; a
    collinear or non-magnetic run ignores one with a warning."""
    state = magnetic_decision(
        _IRON,
        is_magnetic(_IRON),
        human=MagneticConfigHumanInput(moment_direction=(1, 0, 0), **settings),
    )

    assert state.value.moment_direction is None
    assert state.value.angle1 is None
    assert state.value.angle2 is None
    assert "magnetic.moment_direction_ignored" in _codes(state)
    assert "magnetic.soc_moment_direction_defaulted" not in _codes(state)


@pytest.mark.parametrize("scale", [1e-200, 3.0, 1e200])
def test_a_moment_direction_is_a_direction_whatever_its_length(scale: float) -> None:
    """#172: only the direction of [uvw] counts, however small or large
    its components."""
    state = magnetic_decision(
        _HCP_COBALT,
        is_magnetic(_HCP_COBALT),
        human=MagneticConfigHumanInput(
            spin_orbit_coupling=True, moment_direction=(0.0, scale, 0.0)
        ),
    )

    assert state.value.angle1 == {"Co": 90.0}
    assert state.value.angle2 == {"Co": 120.0}


def test_a_moment_along_z_within_rounding_noise_has_no_azimuth() -> None:
    """#172: a c axis along z up to rounding noise in its y component
    (1e-14 A) is written as angle1 = angle2 = 0, not with the arbitrary
    azimuth of the noise."""
    noisy = Structure(
        Lattice([[2.87, 0, 0], [0, 2.87, 0], [0, 1e-14, 2.87]]),
        ["Fe", "Fe"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )

    state = magnetic_decision(
        noisy,
        is_magnetic(noisy),
        human=MagneticConfigHumanInput(spin_orbit_coupling=True),
    )

    assert state.value.angle1 == {"Fe": 0.0}
    assert state.value.angle2 == {"Fe": 0.0}


def test_a_zero_moment_direction_is_rejected() -> None:
    with pytest.raises(ValidationError, match="moment_direction"):
        MagneticConfigHumanInput(moment_direction=(0, 0, 0))


def _same_sites(cell: Structure, structure: Structure) -> bool:
    """Whether ``cell`` has ``structure``'s lattice, elements and
    positions, in order -- the FM identity pass-through, whatever species
    and labels the split gave its sites."""
    return (
        np.allclose(cell.lattice.matrix, structure.lattice.matrix)
        and np.allclose(cell.frac_coords, structure.frac_coords)
        and [site.specie.symbol for site in cell]
        == [site.specie.symbol for site in structure]
    )


def test_the_cell_is_the_input_structure_by_default() -> None:
    """AFM species-splitting (v2 epic 9, #9) is opt-in via
    ``magnetic_ordering="afm"`` -- without it, the cell keeps the input's
    sites (the FM identity pass-through), every one seeded positive."""
    state = magnetic_cell(_IRON, is_magnetic(_IRON))

    assert _same_sites(state.value.structure, _IRON)
    assert _spins(state.value.structure, "Fe") == {1.0}
    assert state.value.ordering == OrderingRecord(requested=None, applied="fm")
    assert np.allclose(state.value.cell_in_input_basis, np.eye(3))


def _afm_rock_salt(structure: Structure, axis: int = 2) -> Structure:
    """A spin-decorated 4-site cell of a 2-site rock-salt input, its two
    Ni up and down along the doubled lattice vector ``axis`` (c by
    default), as the enumerator returns one."""
    scaling = [1, 1, 1]
    scaling[axis] = 2
    supercell = structure * scaling
    spins = iter((5.0, -5.0))
    return Structure(
        supercell.lattice,
        [
            Species("Ni", spin=next(spins))
            if site.specie.symbol == "Ni"
            else site.specie
            for site in supercell
        ],
        supercell.frac_coords,
    )


_ROCK_SALT_NIO = Structure(
    Lattice.from_parameters(2.95, 2.95, 2.95, 60, 60, 60),
    ["Ni", "O"],
    [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
)
_AFM = MagneticConfigHumanInput(magnetic_ordering="afm")


@pytest.fixture
def afm_candidate(monkeypatch) -> Structure:
    """The one antiferromagnetic candidate a stubbed enumeration returns
    for ``_ROCK_SALT_NIO`` (the real enumerator runs in a worker process,
    out of a monkeypatch's reach)."""
    candidate = _afm_rock_salt(_ROCK_SALT_NIO)
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((candidate, "afm"))
    )
    return candidate


def test_an_applied_ordering_is_the_cell_with_its_basis_in_the_input(
    afm_candidate,
) -> None:
    """#128: the applied candidate is the cell everything downstream reads,
    labelled by sublattice, with the ordering asked for and applied, and
    its lattice in the input's basis -- here a doubling along c. A
    translation maps its up Ni onto the down one, so once seeded its net
    moment is zero by symmetry: it is compensated (#138), which
    magnetic_config decides on the seeds (#185)."""
    state = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), _AFM)

    cell = state.value
    assert len(cell.structure) == 4
    assert sorted({site.label for site in cell.structure}) == ["Ni1", "Ni2", "O"]
    assert cell.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=(),
    )
    assert magnetic_config(state).value.compensated is True
    assert np.allclose(cell.cell_in_input_basis, np.diag([1.0, 1.0, 2.0]))
    assert np.allclose(
        cell.structure.lattice.matrix,
        np.array(cell.cell_in_input_basis) @ _ROCK_SALT_NIO.lattice.matrix,
    )


def test_seeds_are_set_on_the_applied_cell_once_z_valence_is_known(
    afm_candidate,
) -> None:
    """The second step scales the cell's sublattice seeds by the selected
    pseudopotential's z_valence: Ni's 5 Bohr magneton target over 18
    electrons, with opposite signs on the two Ni sublattices. O, off the
    sublattice, starts at 0 as in QE's own AFM references (#170); aiida's
    +0.1 on every species is the ferromagnetic default only."""
    cell = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), _AFM)

    state = magnetic_config(cell, z_valences={"Ni": 18.0, "O": 6.0})
    ferromagnetic = magnetic_decision(
        _ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), z_valences={"Ni": 18.0}
    )

    assert state.value.cell is cell.value.structure
    assert state.value.ordering == cell.value.ordering
    assert state.value.compensated is True
    assert state.value.starting_magnetization == {
        "Ni1": 5.0 / 18.0,
        "Ni2": -5.0 / 18.0,
        "O": 0.0,
    }
    assert ferromagnetic.value.starting_magnetization == {"Ni": 5.0 / 18.0, "O": 0.1}
    assert state.source == cell.source


def test_a_compensated_ordering_seeds_no_net_moment(afm_candidate) -> None:
    """Only the sublattice is seeded on an applied ordering (#170), so
    NiO's AFM-II cell starts from 5 uB up, 5 down and nothing on O (#131);
    the ferromagnetic default seeds the O too."""
    z_valences = {"Ni": 18.0, "O": 6.0}
    cell = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), _AFM)

    ordered = magnetic_config(cell, z_valences=z_valences)
    ferromagnetic = magnetic_decision(
        _ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), z_valences=z_valences
    )

    assert ordered.value.seeded_moment == pytest.approx(0.0, abs=1e-12)
    assert ferromagnetic.value.seeded_moment == pytest.approx(5.6)


def test_a_human_starting_magnetization_is_checked_against_the_applied_cell(
    afm_candidate,
) -> None:
    """The labels a starting_magnetization may use are the written cell's
    (Ni1/Ni2), not the uploaded structure's. An element key would set both
    sublattices the ordering seeds apart to one value, so it is refused
    and the reason names the labels to set instead (#185, the ambiguity
    #46 guards against)."""
    split = MagneticConfigHumanInput(
        magnetic_ordering="afm", starting_magnetization={"Ni1": 0.5, "Ni2": -0.5}
    )
    unsplit = MagneticConfigHumanInput(
        magnetic_ordering="afm", starting_magnetization={"Ni": 0.5}
    )

    accepted = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), split)
    refused = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), unsplit)

    assert accepted.ok
    assert isinstance(refused, Blocked)
    assert refused.root_cause() == (
        "starting_magnetization cannot set 'Ni' by element: the applied "
        "magnetic ordering seeds its sites differently (labels Ni1, Ni2); "
        "set each of those labels instead"
    )


_CIF_LABELLED_NIO = Structure(
    _ROCK_SALT_NIO.lattice,
    ["Ni", "O"],
    [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    labels=["Ni1", "O1"],
)
"""Rock-salt NiO as the MC3D mc3d-29856 CIF labels it: Ni1 and O1, while
the input names its species Ni and O."""


def test_an_element_key_sets_every_site_of_that_element() -> None:
    """#185: {"Ni": 0.5} on the CIF of NiO was refused ("unknown site
    label(s) ['Ni']; this structure's real labels are ['Ni1', 'O1']"),
    though the input and records.magnetic name the species Ni. An element
    symbol is shorthand for all of that element's sites; O, left out,
    keeps its computed seed."""
    human = MagneticConfigHumanInput(starting_magnetization={"Ni": 0.5})

    state = magnetic_decision(
        _CIF_LABELLED_NIO,
        is_magnetic(_CIF_LABELLED_NIO),
        z_valences={"Ni": 18.0, "O": 6.0},
        human=human,
    )

    assert state.ok
    assert state.value.starting_magnetization == {"Ni": 0.5, "O": 0.1}
    assert state.value.human_seeded_labels == ("Ni",)
    assert state.value.site_labels == ("Ni1", "O1")
    assert state.provenance.field_sources["starting_magnetization"] == "human"


def test_a_partial_override_keeps_the_computed_seeds_it_leaves_out(
    afm_candidate,
) -> None:
    """#185: {"Ni1": 0.5} with afm was accepted and wrote
    starting_magnetization(1) = 0.5 alone, so Ni2 and O started at 0
    while magnetic.afm_ordering_applied still reported the AFM ordering;
    pw.x converged that deck to a near-zero net moment, 7.2 eV per cell
    above the seeded AFM-II one. The request is merged per label onto the
    computed seeds, and records.magnetic names the labels it set."""
    human = MagneticConfigHumanInput(
        magnetic_ordering="afm", starting_magnetization={"Ni1": 0.5}
    )

    state = magnetic_decision(
        _ROCK_SALT_NIO,
        is_magnetic(_ROCK_SALT_NIO),
        z_valences={"Ni": 18.0, "O": 6.0},
        human=human,
    )

    assert state.value.ordering.applied == "afm-1"
    assert state.value.starting_magnetization == {
        "Ni1": 0.5,
        "Ni2": -5.0 / 18.0,
        "O": 0.0,
    }
    assert state.value.human_seeded_labels == ("Ni1",)
    assert set(state.value.site_labels) == {"Ni1", "Ni2", "O"}


def test_a_label_key_beats_an_element_key_for_its_own_sites() -> None:
    """A label narrows an element key: on a ferromagnetic cell labelled
    Ni1/Ni2 (one computed seed for every Ni), {"Ni": 0.5, "Ni1": -0.5}
    starts the Ni1 site at -0.5 and the Ni2 site at 0.5."""
    doubled = _ROCK_SALT_NIO * (1, 1, 2)
    labelled = Structure(
        doubled.lattice,
        doubled.species,
        doubled.frac_coords,
        labels=[
            "Ni1" if index == 0 else "Ni2" if site.specie.symbol == "Ni" else "O"
            for index, site in enumerate(doubled)
        ],
    )
    human = MagneticConfigHumanInput(starting_magnetization={"Ni": 0.5, "Ni1": -0.5})

    state = magnetic_cell(labelled, is_magnetic(labelled), human)

    spins = {
        label: site.specie.spin
        for label, site in zip(labelled.labels, state.value.structure, strict=True)
        if site.specie.symbol == "Ni"
    }
    assert spins == {"Ni1": -0.5, "Ni2": 0.5}


def test_an_unknown_key_is_refused_naming_the_labels_and_element_keys() -> None:
    """#46: a key that names no site must not silently seed nothing. The
    reason lists the labels of the cell the request applies to and the
    element symbols that set all of an element's sites."""
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )

    state = magnetic_cell(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        human=MagneticConfigHumanInput(starting_magnetization={"Fe2": 0.5}),
    )

    assert isinstance(state, Blocked)
    assert state.root_cause() == (
        "starting_magnetization has unknown key(s) Fe2; it takes this "
        "cell's site labels (Fe0, Fe1) or an element symbol for all of that "
        "element's sites (Fe)"
    )


def test_a_run_without_spin_polarization_still_lists_its_site_labels() -> None:
    """The labels a starting_magnetization would take are in
    records.magnetic before any is set (#185)."""
    labelled = Structure(
        _DIAMOND_SILICON.lattice,
        ["Si", "Si"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
        labels=["Si1", "Si2"],
    )

    state = magnetic_decision(labelled, is_magnetic(labelled), z_valences={"Si": 4.0})

    assert not state.value.spin_polarized
    assert state.value.starting_magnetization is None
    assert state.value.site_labels == ("Si1", "Si2")
    assert state.value.human_seeded_labels == ()


@pytest.mark.parametrize("value", [1.5, 1.0, -1.0])
def test_a_starting_magnetization_is_a_fraction_strictly_inside_minus_one_to_one(
    value: float,
) -> None:
    """QE's starting_magnetization is a fraction of the species' valence
    charge. From QE 7.3 a value of magnitude 1 or more turns every species'
    value into a moment in Bohr magnetons, divided by its valence
    (PW/src/input.f90:1441-1442), so it is refused, not rescaled."""
    with pytest.raises(ValidationError):
        MagneticConfigHumanInput(starting_magnetization={"Fe": value})
    assert MagneticConfigHumanInput(starting_magnetization={"Fe": 0.99})


def test_balanced_spin_counts_without_a_spin_reversing_operation_are_not_compensated(
    monkeypatch,
) -> None:
    """One up and one down Ni, but one O moved towards the up Ni: no
    operation maps the up site onto the down one, so the moment is not
    zero by symmetry, however the spins count up."""
    candidate = _afm_rock_salt(_ROCK_SALT_NIO)
    oxygen = next(
        index for index, site in enumerate(candidate) if site.specie.symbol == "O"
    )
    candidate.translate_sites([oxygen], [0.0, 0.0, 0.02])
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((candidate, "afm"))
    )

    state = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), _AFM)

    spins = [site.specie.spin for site in state.value.structure if site.label != "O"]
    assert sorted(spins) == [-1.0, 1.0]
    assert state.value.ordering.applied == "afm-1"
    assert magnetic_config(state).value.compensated is False


def test_opposite_seeds_on_the_uploaded_cell_are_not_compensated() -> None:
    """Only an applied antiferromagnetic ordering is compensated (#138):
    opposite starting magnetizations set by label on the uploaded bcc Fe
    pair cancel by symmetry, but the ordering applied is the ferromagnetic
    identity, so a non-metal gets smearing."""
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )

    state = magnetic_decision(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        z_valences={"Fe": 16.0},
        human=MagneticConfigHumanInput(
            starting_magnetization={"Fe0": 0.5, "Fe1": -0.5}
        ),
    )

    assert state.value.ordering.applied == "fm"
    assert state.value.starting_magnetization == {"Fe1": 0.5, "Fe2": -0.5}
    assert state.value.seeded_moment == pytest.approx(0.0)
    assert state.value.compensated is False


@pytest.mark.parametrize(
    ("seeds", "compensated"),
    [
        pytest.param({"Ni1": 0.5, "Ni2": -0.5}, True, id="both-opposite"),
        pytest.param({"Ni1": 0.5, "Ni2": -0.3}, False, id="both-unequal"),
        pytest.param({"Ni1": 0.5, "Ni2": -0.495}, False, id="both-nearly-opposite"),
        pytest.param({"Ni1": 0.004, "Ni2": 0.004}, False, id="both-small-parallel"),
        pytest.param({"Ni1": 5.0 / 18.0}, True, id="Ni1-restates-its-seed"),
        pytest.param({"Ni2": -5.0 / 18.0}, True, id="Ni2-restates-its-seed"),
        # The seed as scf.in writes it, to 12 significant digits (#178).
        pytest.param({"Ni2": -0.277777777778}, True, id="Ni2-copied-from-scf.in"),
        pytest.param({"Ni1": 0.277778}, True, id="Ni1-to-six-digits"),
        pytest.param({"Ni1": 0.27778}, False, id="Ni1-to-five-digits"),
        pytest.param({"Ni1": 0.2778}, False, id="Ni1-to-four-digits"),
        pytest.param({"Ni1": 0.5}, False, id="Ni1-differs"),
    ],
)
def test_compensation_is_decided_on_the_seeds_as_written(
    afm_candidate, seeds: dict[str, float], compensated: bool
) -> None:
    """A human starting_magnetization on the applied cell is merged onto its
    computed seeds (Ni's 5/18 with an 18-electron pseudopotential, up on
    Ni1, down on Ni2), and whether the start is compensated is decided on
    the seeds as written, to rounding (#185). Restating one sublattice's
    computed seed, to six significant digits or more, leaves the seeds
    opposite, compensated, although the cell's classes then pair a
    requested value with the other sublattice's bare spin sign. A rounder
    value, or seeds within 0.01 of opposite (spglib's default tolerance
    here), start a net moment and are not."""
    state = magnetic_decision(
        _ROCK_SALT_NIO,
        is_magnetic(_ROCK_SALT_NIO),
        z_valences={"Ni": 18.0, "O": 6.0},
        human=MagneticConfigHumanInput(
            magnetic_ordering="afm", starting_magnetization=seeds
        ),
    )

    assert state.value.compensated is compensated
    # Two Ni seeds opposite to 1e-6 start at most 1.8e-5 Bohr magnetons
    # (18 electrons each): 4e-6 for the six-digit copy, 4e-5 for five digits.
    assert (state.value.seeded_moment == pytest.approx(0.0, abs=2e-5)) is compensated


def _spinel_fe3o4() -> Structure:
    """Spinel Fe3O4 (Fd-3m, origin choice 1): tetrahedral Fe at 8a,
    octahedral Fe at 16d, O at 32e; its primitive cell has 14 sites, 6 of
    them Fe."""
    return Structure.from_spacegroup(
        "Fd-3m",
        Lattice.cubic(8.396),
        ["Fe", "Fe", "O"],
        [[0, 0, 0], [0.625, 0.625, 0.625], [0.380, 0.380, 0.380]],
    ).get_primitive_structure()


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_a_ferrimagnetic_candidate_with_balanced_spins_is_not_compensated() -> None:
    """#138: spinel's R-3m candidate has 3 Fe up and 3 down, but both
    tetrahedral Fe point down: no operation maps a tetrahedral site onto
    an octahedral one, so it is a ferrimagnet, not compensated. Every
    NiO candidate is."""
    spinel = _spinel_fe3o4()
    candidates, _warning = enumerate_magnetic_orderings(spinel, local_moments(spinel))
    [label] = [
        label
        for label, cell in candidates
        if label != "fm" and cell.get_space_group_info()[0] == "R-3m"
    ]

    ferrimagnet = magnetic_decision(
        spinel,
        is_magnetic(spinel),
        human=MagneticConfigHumanInput(magnetic_ordering=label),
    ).value
    nio = magnetic_decision(
        _ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), human=_AFM
    ).value

    assert len(ferrimagnet.cell) == 14
    iron_spins = [
        site.specie.spin for site in ferrimagnet.cell if site.specie.symbol == "Fe"
    ]
    assert sorted(iron_spins) == [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]
    assert ferrimagnet.compensated is False
    assert nio.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2",),
    )
    assert nio.compensated is True


def _afm_8_site_rock_salt(structure: Structure) -> Structure:
    """A spin-decorated 8-site candidate of a 2-site rock-salt input."""
    supercell = structure * (2, 2, 1)
    spins = iter((5.0, -5.0, -5.0, 5.0))
    return Structure(
        supercell.lattice,
        [
            Species("Ni", spin=next(spins))
            if site.specie.symbol == "Ni"
            else site.specie
            for site in supercell
        ],
        supercell.frac_coords,
    )


def test_afm_applies_the_first_listed_candidate_and_records_its_label(
    monkeypatch,
) -> None:
    """#170: plain afm and the label the listing gives the same candidate
    write the same cell, so a listed candidate fed back to a run cannot
    diverge from the afm path. afm-1 is the smallest candidate, wherever
    the enumerator put it."""
    small = _afm_rock_salt(_ROCK_SALT_NIO)
    large = _afm_8_site_rock_salt(_ROCK_SALT_NIO)
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _enumerating((large, "afm"), (small, "afm")),
    )

    def cell(ordering: str):
        return magnetic_cell(
            _ROCK_SALT_NIO,
            is_magnetic(_ROCK_SALT_NIO),
            MagneticConfigHumanInput(magnetic_ordering=ordering),
        )

    states = [cell("afm"), cell("afm-1"), cell("afm-2")]
    afm, first, second = (state.value for state in states)

    assert [magnetic_config(state).value.compensated for state in states] == [
        True,
        True,
        True,
    ]
    assert afm.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=(),
    )
    assert first.ordering == OrderingRecord(
        requested="afm-1",
        applied="afm-1",
        criterion="requested",
        alternatives=(),
    )
    assert second.ordering == OrderingRecord(
        requested="afm-2",
        applied="afm-2",
        criterion="requested",
        alternatives=(),
    )
    assert afm.structure == first.structure
    assert [site.label for site in afm.structure] == [
        site.label for site in first.structure
    ]
    assert len(first.structure) == 4
    assert len(second.structure) == 8


def test_afm_labels_follow_a_canonical_order_not_the_enumerator_s(
    monkeypatch,
) -> None:
    """#170: pymatgen orders candidates of one size and space group by
    the order enumlib's output files are read in, which can differ between
    the host that lists and the one that runs. afm-<n> names the same cell
    whatever order the enumerator returns them in."""
    along_a = _afm_rock_salt(_ROCK_SALT_NIO, axis=0)
    along_c = _afm_rock_salt(_ROCK_SALT_NIO, axis=2)
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))

    listings = []
    for order in ((along_a, along_c), (along_c, along_a)):
        monkeypatch.setattr(
            magnetic_config_module,
            "enumerate_orderings",
            _enumerating(*((candidate, "afm") for candidate in order)),
        )
        candidates, _warning = enumerate_magnetic_orderings(
            _ROCK_SALT_NIO, local_moments(_ROCK_SALT_NIO)
        )
        listings.append(
            {label: cell.lattice.matrix.round(6).tolist() for label, cell in candidates}
        )

    assert list(listings[0]) == ["fm", "afm-1", "afm-2"]
    assert listings[0] == listings[1]


def test_an_unknown_afm_label_is_blocked_and_names_the_available_ones(
    afm_candidate,
) -> None:
    """#170: a label names one listed candidate; one this structure does
    not have is refused rather than written as another cell."""
    state = magnetic_cell(
        _ROCK_SALT_NIO,
        is_magnetic(_ROCK_SALT_NIO),
        MagneticConfigHumanInput(magnetic_ordering="afm-2"),
    )

    assert isinstance(state, Blocked)
    assert "'afm-2'" in state.root_cause()
    assert "fm, afm-1" in state.root_cause()


def test_a_listed_label_is_blocked_with_the_reason_none_can_be_listed(
    monkeypatch,
) -> None:
    """#170: plain afm degrades to ferromagnetic order with a warning, but
    a request for one listed candidate cannot be met by writing another."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    state = magnetic_cell(
        _ROCK_SALT_NIO,
        is_magnetic(_ROCK_SALT_NIO),
        MagneticConfigHumanInput(magnetic_ordering="afm-1"),
    )

    assert isinstance(state, Blocked)
    assert "'afm-1'" in state.root_cause()
    assert "enumlib" in state.root_cause()


@pytest.mark.parametrize("value", ["afm-0", "afm-01", "AFM", "afm1", "ferri"])
def test_magnetic_ordering_takes_fm_afm_or_a_listed_label(value: str) -> None:
    with pytest.raises(ValidationError):
        MagneticConfigHumanInput(magnetic_ordering=value)


def test_a_human_split_is_a_species_split_of_the_cell_symmetry_sees() -> None:
    """#170: two Fe given opposite starting magnetizations are two pw.x
    species, so the cell symmetry_eff and n_irr_k read must hold them as
    two types (simple cubic B2, Pm-3m), not bcc Im-3m with the split
    applied only by the writer."""
    two_iron_sites = Structure(
        Lattice.cubic(2.87),
        ["Fe", "Fe"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Fe0", "Fe1"],
    )

    state = magnetic_decision(
        two_iron_sites,
        is_magnetic(two_iron_sites),
        human=MagneticConfigHumanInput(
            starting_magnetization={"Fe0": 0.5, "Fe1": -0.5}
        ),
    )

    cell = state.value.cell
    assert [site.label for site in cell] == ["Fe1", "Fe2"]
    assert state.value.starting_magnetization == {"Fe1": 0.5, "Fe2": -0.5}
    assert symmetry(cell).value.space_group_symbol == "Pm-3m"
    assert symmetry(two_iron_sites).value.space_group_symbol == "Im-3m"


def test_the_cell_has_one_species_per_element_whatever_the_upload_s_labels() -> None:
    """Many CIFs label every site (Si1..Si40) with no physical meaning: the
    cell carries one species per element, so neither symmetry nor the
    writer sees them as distinct (moved from the writer, #170)."""
    labelled = Structure(
        Lattice.cubic(5.43),
        ["Si", "Si", "Si"],
        [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25], [0.5, 0.5, 0.0]],
        labels=["Si1", "Si7", "Si23"],
    )

    state = magnetic_cell(
        labelled,
        is_magnetic(labelled),
        MagneticConfigHumanInput(spin_polarized=False),
    )

    assert [site.label for site in state.value.structure] == ["Si", "Si", "Si"]


def test_a_blocked_cell_blocks_the_starting_moments() -> None:
    state = magnetic_config(Blocked(by="unknown site label"), z_valences={"Fe": 16.0})

    assert isinstance(state, Blocked)
    assert state.root_cause() == "unknown site label"


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_afm_ordering_finds_a_real_compensated_split() -> None:
    """v2 epic 9 (#9)'s AFM acceptance scenario: rock-salt FeO has one Fe
    sublattice by symmetry, so a real, compensated antiferromagnetic
    ordering needs distinguishing the two Fe sites -- proving
    the cell genuinely has more species than structure, not just that the
    type accepts it."""
    state = magnetic_decision(
        _ROCK_SALT_FEO,
        is_magnetic(_ROCK_SALT_FEO),
        human=MagneticConfigHumanInput(magnetic_ordering="afm"),
    )

    assert state.ok
    facts = state.value
    assert len(set(facts.cell.species)) > len(set(_ROCK_SALT_FEO.species))
    fe_moments = [
        value
        for label, value in facts.starting_magnetization.items()
        if label.startswith("Fe")
    ]
    assert len(fe_moments) == 2
    assert any(moment > 0 for moment in fe_moments)
    assert any(moment < 0 for moment in fe_moments)
    assert any(
        warning.code == "magnetic.afm_ordering_applied" for warning in facts.warnings
    )


def test_afm_ordering_degrades_when_enumlib_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    state = magnetic_cell(
        _ROCK_SALT_FEO,
        is_magnetic(_ROCK_SALT_FEO),
        human=MagneticConfigHumanInput(magnetic_ordering="afm"),
    )

    assert state.ok
    assert state.value.structure == _ROCK_SALT_FEO
    assert state.value.ordering == OrderingRecord(requested="afm", applied="fm")
    assert any(
        warning.code == "magnetic.afm_ordering_unavailable"
        and "enumlib" in warning.message
        for warning in state.value.warnings
    )


_CLASSIFIED_NON_MAGNETIC = Resolved("non_magnetic", Provenance(source="ml"))
"""What the ML tier answered for bcc Cr and La2CuO4 (#145)."""

_BCC_CHROMIUM = Structure(
    Lattice.cubic(2.88), ["Cr", "Cr"], [[0, 0, 0], [0.5, 0.5, 0.5]]
)


def test_an_afm_request_turns_spin_polarization_on_whatever_the_classifier_says(
    afm_candidate,
) -> None:
    """#145: magnetic_ordering=afm is a spin request, like tot_magnetization
    and starting_magnetization (#34). On a structure classified
    non-magnetic it used to be accepted and dropped: no nspin, no ordering,
    no warning."""
    state = magnetic_cell(_ROCK_SALT_NIO, _CLASSIFIED_NON_MAGNETIC, _AFM)

    assert state.value.spin_polarized is True
    assert state.source == "human"
    assert state.value.magnetic_elements == ("Ni",)
    assert state.value.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=(),
    )
    assert magnetic_config(state).value.compensated is True
    assert len(state.value.structure) == 4


def test_an_afm_request_that_cannot_be_ordered_still_leaves_a_record(
    monkeypatch,
) -> None:
    """#145: with enumlib missing, an afm request on a structure classified
    non-magnetic runs spin-polarized and says why it stayed
    ferromagnetic."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    state = magnetic_cell(_BCC_CHROMIUM, _CLASSIFIED_NON_MAGNETIC, _AFM)

    assert state.value.spin_polarized is True
    assert state.source == "human"
    assert state.value.ordering == OrderingRecord(requested="afm", applied="fm")
    (warning,) = state.value.warnings
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "enumlib" in warning.message


@pytest.mark.parametrize(
    ("magnetization", "codes"),
    [
        ({}, ["magnetic.ordering_ignored_spin_polarized_false"]),
        (
            {"tot_magnetization": 2.0},
            [
                "magnetic.magnetization_ignored_spin_polarized_false",
                "magnetic.ordering_ignored_spin_polarized_false",
            ],
        ),
    ],
    ids=["ordering", "ordering+tot_magnetization"],
)
def test_explicit_spin_polarized_false_keeps_an_afm_request_off_and_warns(
    magnetization: dict[str, float], codes: list[str]
) -> None:
    """#145: an explicit spin_polarized=false wins over magnetic_ordering=afm,
    as it does over the magnetization keys, and says that the ordering was
    ignored -- next to the magnetization warning when those were given
    too."""
    human = MagneticConfigHumanInput(
        spin_polarized=False, magnetic_ordering="afm", **magnetization
    )

    state = magnetic_cell(_BCC_CHROMIUM, is_magnetic(_BCC_CHROMIUM), human)

    assert state.value.spin_polarized is False
    assert state.source == "human"
    assert state.value.structure == _BCC_CHROMIUM
    assert state.value.ordering == OrderingRecord(requested="afm", applied=None)
    assert sorted(warning.code for warning in state.value.warnings) == codes
    (ignored,) = (
        warning
        for warning in state.value.warnings
        if warning.code == "magnetic.ordering_ignored_spin_polarized_false"
    )
    assert ignored.level == "warning"
    assert "magnetic_ordering" in ignored.message
    assert "spin_polarized" in ignored.message


def test_an_fm_ordering_is_a_spin_request_on_the_input_cell() -> None:
    """#170: ``"fm"`` is the listing's ferromagnetic candidate, generated
    from the listed structure by its label alone. Like an afm label it asks
    for a spin-polarized run, on the input cell; read as the unset default,
    it wrote an unpolarized deck for a structure classified non-magnetic."""
    human = MagneticConfigHumanInput(magnetic_ordering="fm")

    state = magnetic_cell(_BCC_CHROMIUM, _CLASSIFIED_NON_MAGNETIC, human)

    assert state.value.spin_polarized is True
    assert state.source == "human"
    assert _same_sites(state.value.structure, _BCC_CHROMIUM)
    assert (state.value.ordering.requested, state.value.ordering.applied) == (
        "fm",
        "fm",
    )
    assert state.value.warnings == ()


def test_explicit_spin_polarized_false_ignores_an_fm_ordering_and_warns() -> None:
    human = MagneticConfigHumanInput(spin_polarized=False, magnetic_ordering="fm")

    state = magnetic_cell(_BCC_CHROMIUM, _CLASSIFIED_NON_MAGNETIC, human)

    assert state.value.spin_polarized is False
    assert [warning.code for warning in state.value.warnings] == [
        "magnetic.ordering_ignored_spin_polarized_false"
    ]


def test_an_unset_ordering_leaves_spin_polarization_to_the_classifier() -> None:
    state = magnetic_cell(_BCC_CHROMIUM, _CLASSIFIED_NON_MAGNETIC)

    assert state.value.spin_polarized is False
    assert state.source == "heuristic"
    assert state.value.warnings == ()


def test_a_run_without_spin_polarization_applies_no_ordering() -> None:
    """#187: magnetic_ordering resolves in ``ordering.applied``. A run without
    spin polarization recorded "fm" there, a value that as a setting asks for
    spin polarization, so the Workbench showed it next to spin polarized
    off."""
    state = magnetic_cell(_BCC_CHROMIUM, _CLASSIFIED_NON_MAGNETIC)

    assert state.value.spin_polarized is False
    assert state.value.ordering == OrderingRecord(requested=None, applied=None)


_TENORITE_CUO = Structure.from_spacegroup(
    "C2/c",
    Lattice.monoclinic(4.6837, 3.4226, 5.1288, 99.54),
    ["Cu", "O"],
    [[0.25, 0.25, 0.0], [0.0, 0.4184, 0.25]],
).get_primitive_structure()
"""Tenorite CuO (C2/c, Asbrink & Norrby 1970) in its 4-atom primitive
cell: Cu2+ is d9, and the built-in table gives Cu 4.0 eV."""

_CORRELATED = Resolved(True, Provenance(source="heuristic"))


def _tabulated_u(
    structure: Structure, human: HubbardUHumanInput | None = None
) -> Resolved[HubbardUDecision]:
    return hubbard_u(structure, _CORRELATED, DEFAULT_FUNCTIONAL, human)


_HUBBARD_SPIN = "magnetic.spin_polarized_for_hubbard_open_shell"


def test_a_hubbard_u_on_an_odd_d_count_turns_spin_polarization_on() -> None:
    """#147: the ML tier called tenorite CuO non-magnetic (score 0.101), so
    its +U input went out with nspin=1. A Dudarev U on Cu2+ d9 then has
    4.5 electrons per spin channel to act on, which fill no whole orbital:
    it can neither form the moment nor open the gap. A U on an odd d or f
    count turns spin polarization on, says so, and names what it
    overrode."""
    state = magnetic_cell(
        _TENORITE_CUO, _CLASSIFIED_NON_MAGNETIC, hubbard=_tabulated_u(_TENORITE_CUO)
    )

    assert state.value.spin_polarized is True
    assert state.value.magnetic_elements == ("Cu",)
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {
        "spin_polarized": "heuristic",
        "spin_orbit_coupling": "heuristic",
        "magnetic_ordering": "heuristic",
        "starting_magnetization": "heuristic",
    }
    assert state.provenance.derived_from == ("hubbard",)
    (warning,) = state.value.warnings
    assert warning.code == _HUBBARD_SPIN
    assert warning.level == "warning"
    assert warning.category == "magnetic"
    assert "odd d or f electron count: Cu 3d9." in warning.message
    assert "is_magnetic='non_magnetic' (ml)" in warning.message
    assert "spin_polarized=false" in warning.message


def test_the_hubbard_rule_outranks_an_llm_spin_polarized_false() -> None:
    """#147: the rule sits above the llm's spin_polarized, as above
    is_magnetic; the warning names the llm's answer."""
    llm = MagneticConfigLlmInput(spin_polarized=False)

    without_u = magnetic_cell(_TENORITE_CUO, is_magnetic(_TENORITE_CUO), llm=llm)
    with_u = magnetic_cell(
        _TENORITE_CUO,
        is_magnetic(_TENORITE_CUO),
        llm=llm,
        hubbard=_tabulated_u(_TENORITE_CUO),
    )

    assert (without_u.value.spin_polarized, without_u.source) == (False, "llm")
    assert (with_u.value.spin_polarized, with_u.source) == (True, "heuristic")
    (warning,) = with_u.value.warnings
    assert warning.code == _HUBBARD_SPIN
    assert "the llm's spin_polarized=false" in warning.message


@pytest.mark.parametrize(
    "hubbard",
    [
        None,
        Blocked(by="synthetic failure"),
        Resolved(HubbardUDecision(), Provenance(source="human")),
        _tabulated_u(_TENORITE_CUO, HubbardUHumanInput(u_by_element={"Ni": 6.2})),
    ],
    ids=["no-decision", "unresolved", "no-u", "u-on-another-element"],
)
def test_the_hubbard_rule_needs_a_u_on_the_open_shell(hubbard) -> None:
    """#147: without a U on Cu (no decision, an unresolved one, none at
    all, or one only on an element CuO does not contain) the classifier
    decides."""
    state = magnetic_cell(_TENORITE_CUO, _CLASSIFIED_NON_MAGNETIC, hubbard=hubbard)

    assert state.value.spin_polarized is False
    assert state.provenance.derived_from == ("is_magnetic",)
    assert state.value.warnings == ()


def test_an_explicit_spin_polarized_false_wins_over_the_hubbard_rule() -> None:
    state = magnetic_cell(
        _TENORITE_CUO,
        _CLASSIFIED_NON_MAGNETIC,
        MagneticConfigHumanInput(spin_polarized=False),
        hubbard=_tabulated_u(_TENORITE_CUO),
    )

    assert state.value.spin_polarized is False
    assert state.source == "human"
    assert state.value.warnings == ()


def test_the_hubbard_rule_leaves_a_magnetic_classification_as_it_was() -> None:
    """#147: the rule only changes a spin-unpolarized answer, so a
    classifier that already says magnetic keeps deciding, and the record
    keeps naming it."""
    state = magnetic_cell(
        _TENORITE_CUO, is_magnetic(_TENORITE_CUO), hubbard=_tabulated_u(_TENORITE_CUO)
    )

    assert state.value.spin_polarized is True
    assert state.provenance.derived_from == ("is_magnetic",)
    assert state.value.warnings == ()


def test_a_requested_spin_orbit_coupling_reads_human() -> None:
    """#173: spin_orbit_coupling=true on bcc Fe read 'heuristic' with no
    field_sources, so no record said the user enabled SOC. Spin
    polarization still follows is_magnetic, which the record names."""
    human = MagneticConfigHumanInput(spin_orbit_coupling=True)

    state = magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON), human=human)

    assert state.value.spin_orbit_enabled is True
    assert state.source == "human"
    assert state.provenance.field_sources == {
        "spin_polarized": "heuristic",
        "spin_orbit_coupling": "human",
        "magnetic_ordering": "heuristic",
        "starting_magnetization": "heuristic",
        "moment_direction": "heuristic",
    }
    assert state.provenance.derived_from == ("is_magnetic",)


def test_a_requested_afm_ordering_reads_human(afm_candidate) -> None:
    """#173: the ordering the request asked for is the request's, and so is
    the spin polarization it implies (#145); the seeds are the
    heuristic's."""
    state = magnetic_decision(_ROCK_SALT_NIO, _CLASSIFIED_NON_MAGNETIC, human=_AFM)

    assert state.value.ordering.applied == "afm-1"
    assert state.source == "human"
    assert state.provenance.field_sources == {
        "spin_polarized": "human",
        "spin_orbit_coupling": "heuristic",
        "magnetic_ordering": "human",
        "starting_magnetization": "heuristic",
    }
    assert state.provenance.derived_from == ()


def test_following_is_magnetic_stays_heuristic_and_names_it() -> None:
    """#173: a magnetic record that follows the is_magnetic fact keeps
    'heuristic', whatever tier decided the fact, and links to it."""
    state = magnetic_decision(_BCC_CHROMIUM, _CLASSIFIED_NON_MAGNETIC)

    assert state.value.spin_polarized is False
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {
        "spin_polarized": "heuristic",
        "spin_orbit_coupling": "heuristic",
    }
    assert state.provenance.derived_from == ("is_magnetic",)


def test_requested_moments_read_human_where_the_cell_applies_them() -> None:
    human = MagneticConfigHumanInput(
        tot_magnetization=4.0, starting_magnetization={"Fe": 0.5}
    )

    state = magnetic_decision(_BCC_IRON, is_magnetic(_BCC_IRON), human=human)

    assert state.value.starting_magnetization == {"Fe": 0.5}
    assert state.source == "human"
    assert state.provenance.field_sources == {
        "spin_polarized": "human",
        "spin_orbit_coupling": "heuristic",
        "magnetic_ordering": "heuristic",
        "starting_magnetization": "human",
        "tot_magnetization": "human",
    }
    assert state.provenance.derived_from == ()


def test_requests_an_explicit_spin_polarized_false_ignores_do_not_read_human() -> None:
    """#173: a field the request set but the decision dropped (with its
    warning) is not the request's value, so it gets no entry."""
    human = MagneticConfigHumanInput(
        spin_polarized=False,
        magnetic_ordering="afm",
        tot_magnetization=2.0,
        moment_direction=(0.0, 0.0, 1.0),
    )

    state = magnetic_decision(_BCC_CHROMIUM, is_magnetic(_BCC_CHROMIUM), human=human)

    assert state.provenance.field_sources == {
        "spin_polarized": "human",
        "spin_orbit_coupling": "heuristic",
    }


def test_an_llm_spin_polarization_reads_llm_and_its_ignored_soc_does_not() -> None:
    """The llm tier may decide spin polarization; spin-orbit coupling takes
    only the human switch, so an llm one is not applied."""
    llm = MagneticConfigLlmInput(spin_polarized=True, spin_orbit_coupling=True)

    state = magnetic_cell(_DIAMOND_SILICON, is_magnetic(_DIAMOND_SILICON), llm=llm)

    assert (state.value.spin_polarized, state.value.spin_orbit_enabled) == (
        True,
        False,
    )
    assert state.source == "llm"
    assert state.provenance.field_sources == {
        "spin_polarized": "llm",
        "spin_orbit_coupling": "heuristic",
        "magnetic_ordering": "heuristic",
        "starting_magnetization": "heuristic",
    }
    assert state.provenance.derived_from == ()


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_afm_on_a_54_site_supercell_of_a_one_fe_cell_is_applied() -> None:
    """#171: the ceiling counted all 54 sites of this 3x3x3 supercell and
    kept it ferromagnetic, though pymatgen reduces it to its primitive cell
    first, whose one Fe enumlib orders in about a second."""
    supercell = _ROCK_SALT_FEO * (3, 3, 3)

    state = magnetic_cell(supercell, is_magnetic(supercell), _AFM)

    assert state.value.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2", "afm-3"),
    )
    assert magnetic_config(state).value.compensated is True
    assert any(
        warning.code == "magnetic.afm_ordering_applied"
        for warning in state.value.warnings
    )


def _feo_supercell(scaling: tuple[int, int, int], *, displaced: bool) -> Structure:
    """``_ROCK_SALT_FEO`` repeated by ``scaling``; ``displaced`` moves one O
    off its site, so the supercell is its own primitive cell."""
    supercell = _ROCK_SALT_FEO * scaling
    if displaced:
        oxygen = next(
            index for index, site in enumerate(supercell) if site.specie.symbol == "O"
        )
        supercell.translate_sites([oxygen], [0.02, 0.0, 0.0])
    return supercell


@pytest.mark.parametrize(
    ("scaling", "displaced"),
    [((3, 3, 3), False), ((2, 2, 2), True)],
    ids=["27-Fe-supercell-of-a-1-Fe-cell", "8-Fe-primitive-cell"],
)
def test_afm_enumerates_up_to_eight_magnetic_sites_in_the_primitive_cell(
    monkeypatch, scaling: tuple[int, int, int], displaced: bool
) -> None:
    """#171: what enumlib orders is the sublattice sites of the primitive
    cell, not every atom of the uploaded one."""
    enumerated: list[Structure] = []

    def enumerate_orderings(structure: Structure, **_kwargs):
        enumerated.append(structure)
        return ()

    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", enumerate_orderings
    )
    supercell = _feo_supercell(scaling, displaced=displaced)

    _candidates, warning = enumerate_magnetic_orderings(
        supercell, local_moments(supercell)
    )

    assert len(enumerated) == 1
    assert warning.message == (
        "no antiferromagnetic ordering was found; kept ferromagnetic order."
    )


def test_afm_refuses_more_than_eight_magnetic_sites_in_the_primitive_cell(
    monkeypatch,
) -> None:
    """#171: nine Fe that no translation maps onto each other are past the
    ceiling, which is refused before enumlib runs."""
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _failing_with(AssertionError("enumerated past the ceiling")),
    )
    supercell = _feo_supercell((3, 3, 1), displaced=True)

    state = magnetic_cell(supercell, is_magnetic(supercell), _AFM)

    assert _same_sites(state.value.structure, supercell)
    assert state.value.ordering == OrderingRecord(requested="afm", applied="fm")
    [warning] = _afm_warnings(state.value.warnings)
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert warning.message == (
        "the primitive cell has 9 magnetic sites (Fe), over the 8 this "
        "heuristic enumerates orderings for; kept ferromagnetic order."
    )


def test_the_enumerator_gets_an_interactive_budget(monkeypatch) -> None:
    """#171: pymatgen gives enumlib 5 minutes per call, starts a joblib
    process pool on every call for its bookkeeping, and adds ferrimagnetic
    strategies whose candidates are never antiferromagnetic."""
    received: dict[str, object] = {}

    def enumerate_orderings(_structure: Structure, **kwargs):
        received.update(kwargs)
        return ()

    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", enumerate_orderings
    )

    enumerate_magnetic_orderings(_ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO))

    assert received["automatic"] is False
    assert received["transformation_kwargs"] == {"timeout": 0.5, "n_jobs": 1}


def _canted_nio() -> Structure:
    """Conventional rock-salt NiO with the non-collinear Ni moments a magCIF
    carries as a ``magmom`` site property."""
    nio = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    directions = iter(([1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]))
    nio.add_site_property(
        "magmom",
        [
            Magmom(next(directions) if site.specie.symbol == "Ni" else [0, 0, 0])
            for site in nio
        ],
    )
    return nio


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_afm_seeds_the_sublattice_whatever_moments_the_upload_carries() -> None:
    """pymatgen refuses an input whose own moments are non-collinear; the
    AFM search never reads them, it seeds the sublattice itself."""
    nio = _canted_nio()

    state = magnetic_cell(nio, is_magnetic(nio), _AFM)

    assert state.value.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2",),
    )
    assert magnetic_config(state).value.compensated is True
    assert _spins(state.value.structure, "Ni") == {1.0, -1.0}


def test_afm_ordering_degrades_when_no_antiferromagnetic_ordering_is_found(
    monkeypatch,
) -> None:
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((_IRON, "fm"))
    )

    state = magnetic_cell(
        _IRON,
        is_magnetic(_IRON),
        human=MagneticConfigHumanInput(magnetic_ordering="afm"),
    )

    assert state.ok
    assert state.value.structure == _IRON
    assert any(
        warning.code == "magnetic.afm_ordering_unavailable"
        and "no antiferromagnetic ordering was found" in warning.message
        for warning in state.value.warnings
    )


def _la2cuo4() -> Structure:
    """T-type La2CuO4 (I4/mmm, Materials Project mp-19735): Cu2+ d9 and
    La3+ 4f0."""
    return Structure.from_spacegroup(
        "I4/mmm",
        Lattice.tetragonal(3.78, 13.2),
        ["La", "Cu", "O", "O"],
        [[0, 0, 0.3606], [0, 0, 0], [0, 0.5, 0], [0, 0, 0.1828]],
    )


def _fept() -> Structure:
    """L1_0 FePt (P4/mmm, MC3D mc3d-49510): Pt's moment is induced by Fe."""
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
"""alpha-O2 (MC3D mc3d-25060): its moment is the O2 molecule's triplet, no
site carries a local d or f moment."""

_URANIUM_SULFIDE = Structure.from_spacegroup(
    "Fm-3m", Lattice.cubic(5.489), ["U", "S"], [[0, 0, 0], [0.5, 0.5, 0.5]]
)
"""Rock-salt US: no oxidation-state guess, and U's one common state (+6) is
5f0, so its local moments are undecidable."""


def _spins(cell: Structure, element: str) -> set[float]:
    return {
        getattr(site.specie, "spin", None) or 0.0
        for site in cell
        if site.specie.symbol == element
    }


def _afm_warnings(warnings) -> list:
    return [warning for warning in warnings if warning.code.startswith("magnetic.afm_")]


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_afm_orders_the_open_shell_cu_of_la2cuo4_and_never_la() -> None:
    """#143: the sublattice is the sites with a local moment. Seeding 4f0
    La3+ too let La carry the compensating spin while both Cu stayed
    parallel (afm-7 converged to Cu-FM on pw.x)."""
    la2cuo4 = _la2cuo4()

    state = magnetic_cell(la2cuo4, is_magnetic(la2cuo4), _AFM)

    cell = state.value
    assert cell.magnetic_elements == ("Cu",)
    assert cell.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2", "afm-3"),
    )
    assert _spins(cell.structure, "Cu") == {1.0, -1.0}
    assert _spins(cell.structure, "La") == {0.0}
    assert {site.label for site in cell.structure} == {"Cu1", "Cu2", "La", "O"}
    assert magnetic_config(state).value.compensated is True


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_afm_on_fept_splits_fe_in_a_doubled_cell_not_fe_against_pt() -> None:
    """#143: with Pt seeded too, the 2-site input cell itself (Fe up, Pt
    down) was applied as 'antiferromagnetic' and relaxed to the
    ferromagnetic state. Fe alone needs at least a doubled cell."""
    fept = _fept()

    state = magnetic_cell(fept, is_magnetic(fept), _AFM)

    cell = state.value
    assert cell.magnetic_elements == ("Fe",)
    assert cell.ordering.applied == "afm-1"
    assert len(cell.structure) == 4
    assert _spins(cell.structure, "Fe") == {1.0, -1.0}
    assert _spins(cell.structure, "Pt") == {0.0}
    assert {site.label for site in cell.structure} == {"Fe1", "Fe2", "Pt"}


@pytest.mark.parametrize(
    ("structure", "human"),
    [
        (_SOLID_OXYGEN, _AFM),
        (
            _DIAMOND_SILICON,
            MagneticConfigHumanInput(magnetic_ordering="afm", spin_polarized=True),
        ),
    ],
    ids=["solid-O2-radical", "closed-shell-Si"],
)
def test_afm_without_a_moment_bearing_site_is_refused_before_enumlib(
    monkeypatch, structure: Structure, human: MagneticConfigHumanInput
) -> None:
    """#143: an empty sublattice reached pymatgen, whose 'Not detected as
    magnetic' text came back as the reason. It is caught first, under its
    own code naming the supported action."""
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _failing_with(AssertionError("enumerated an empty sublattice")),
    )

    state = magnetic_cell(structure, is_magnetic(structure), human)

    assert state.ok
    assert _same_sites(state.value.structure, structure)
    assert state.value.magnetic_elements == ()
    assert state.value.ordering == OrderingRecord(requested="afm", applied="fm")
    [warning] = _afm_warnings(state.value.warnings)
    assert warning.code == "magnetic.afm_no_open_shell_sites"
    assert warning.level == "warning"
    assert "local d or f moment" in warning.message
    assert "starting_magnetization per site label" in warning.message
    assert "pymatgen" not in warning.message


def test_afm_with_undecidable_local_moments_reports_why(monkeypatch) -> None:
    """#143: 'no open-shell sites' would be false when the model cannot
    tell; the warning carries local_moments' own reason instead."""
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _failing_with(AssertionError("enumerated an undecided sublattice")),
    )

    state = magnetic_cell(_URANIUM_SULFIDE, is_magnetic(_URANIUM_SULFIDE), _AFM)

    assert state.ok
    assert state.value.spin_polarized is True
    assert state.value.magnetic_elements == ()
    assert state.value.ordering == OrderingRecord(requested="afm", applied="fm")
    [warning] = _afm_warnings(state.value.warnings)
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "could not be determined" in warning.message
    assert "U (+6)" in warning.message
    assert "starting_magnetization per site label" in warning.message


def test_enumerate_magnetic_orderings_is_just_fm_when_enumlib_is_missing(
    monkeypatch,
) -> None:
    """#87's listing capability degrades the same way ``magnetic_cell``
    does: no enumlib means no antiferromagnetic candidates, not an error."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    candidates, warning = enumerate_magnetic_orderings(
        _ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO)
    )

    assert candidates == (("fm", _ROCK_SALT_FEO),)
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "enumlib" in warning.message


def test_enumerate_magnetic_orderings_never_picks_a_winner(monkeypatch) -> None:
    """Unlike ``magnetic_cell``, listing every candidate is the
    whole point -- #87's mMACE ranking (or a human) picks the winner, not
    this function."""
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _enumerating((_ROCK_SALT_FEO.copy(), "afm"), (_ROCK_SALT_FEO.copy(), "afm")),
    )

    candidates, warning = enumerate_magnetic_orderings(
        _ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO)
    )

    labels = [label for label, _structure in candidates]
    assert labels == ["fm", "afm-1", "afm-2"]
    assert warning is None


@pytest.mark.parametrize(
    "installed",
    [(), ("enum.x",), ("multienum.x",), ("makeStr.py",), ("makestr.x", "makeStr.x")],
)
def test_afm_enumeration_needs_both_enumlib_executables(
    monkeypatch, installed: tuple[str, ...]
) -> None:
    """pymatgen refuses to enumerate without enum.x/multienum.x *and* a
    structure maker (#136), so a missing one is a reason, not a call."""
    monkeypatch.setattr(shutil, "which", _on_path(*installed))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _failing_with(AssertionError("enumerated without both executables")),
    )

    candidates, warning = enumerate_magnetic_orderings(
        _ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO)
    )

    assert candidates == (("fm", _ROCK_SALT_FEO),)
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "enumlib" in warning.message
    assert "makeStr.py" in warning.message


@pytest.mark.parametrize(
    "installed",
    [
        ("enum.x", "makeStr.py"),
        ("multienum.x", "makestr.x"),
        ("enum.x", "makeStr.x"),
    ],
)
def test_any_name_pymatgen_looks_up_counts_as_installed(
    monkeypatch, installed: tuple[str, ...]
) -> None:
    monkeypatch.setattr(shutil, "which", _on_path(*installed))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _enumerating((_ROCK_SALT_FEO.copy(), "afm")),
    )

    candidates, warning = enumerate_magnetic_orderings(
        _ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO)
    )

    assert [label for label, _structure in candidates] == ["fm", "afm-1"]
    assert warning is None


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(2, "No such file or directory", "vasp.3"),
        LinAlgError("Singular matrix"),
        RuntimeError("This shouldn't happen, found neighbors=[]"),
        ValueError("Too many magnetic sites to sensibly perform enumeration."),
        ValueError("Input structure (NiO) is non-collinear."),
    ],
)
def test_an_enumeration_error_that_is_not_an_enumlib_outcome_propagates(
    monkeypatch, error: Exception
) -> None:
    """#136: overlapping enumerations sharing one cwd failed with the first
    three errors (LinAlgError subclasses ValueError), which came back as a
    plausible ferromagnetic-only listing quoting a host path. #171: the
    magnetic-site ceiling and the moment-free input leave pymatgen no other
    ValueError to raise about a structure, so one is a fault too."""
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _failing_with(error)
    )

    with pytest.raises(type(error)):
        enumerate_magnetic_orderings(_ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO))


def test_enumlib_finding_no_ordering_gets_a_fixed_reason(monkeypatch) -> None:
    """pymatgen turns enumlib's EnumError for every cell size it tries into
    ValueError('Unable to enumerate'), the one answer about the structure a
    ValueError still gives (#171)."""
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _failing_with(ValueError("Unable to enumerate")),
    )

    candidates, warning = enumerate_magnetic_orderings(
        _ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO)
    )

    assert candidates == (("fm", _ROCK_SALT_FEO),)
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert warning.message == (
        "enumlib found no ordering of the magnetic sites for this structure; "
        "kept ferromagnetic order."
    )


def test_an_enumlib_timeout_gets_a_fixed_reason_without_the_error_text(
    monkeypatch,
) -> None:
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _failing_with(TimeoutError("Enumeration took more than timeout 0.5 minutes")),
    )

    state = magnetic_cell(
        _ROCK_SALT_FEO,
        is_magnetic(_ROCK_SALT_FEO),
        human=MagneticConfigHumanInput(magnetic_ordering="afm"),
    )

    assert state.value.structure == _ROCK_SALT_FEO
    [warning] = [
        warning
        for warning in state.value.warnings
        if warning.code == "magnetic.afm_ordering_unavailable"
    ]
    assert warning.message == (
        "enumlib did not finish within its 30 s time limit; kept ferromagnetic order."
    )


@pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)
def test_enumerate_magnetic_orderings_finds_the_same_split_relabeling_does() -> None:
    candidates, warning = enumerate_magnetic_orderings(
        _ROCK_SALT_FEO, local_moments(_ROCK_SALT_FEO)
    )

    assert warning is None
    assert candidates[0][0] == "fm"
    assert candidates[0][1] == _ROCK_SALT_FEO
    afm_candidates = candidates[1:]
    assert len(afm_candidates) > 0
    for label, candidate in afm_candidates:
        assert label.startswith("afm-")
        assert len(set(candidate.species)) > len(set(_ROCK_SALT_FEO.species))


def test_a_moment_direction_keeps_its_meaning_on_an_applied_ordering(
    monkeypatch,
) -> None:
    """#172: [uvw] belongs to the uploaded cell. An ordering whose cell has
    another basis (a + b, -a + b, c) writes the moment along the input's b,
    converted through cell_in_input_basis, not along the written cell's
    own second vector (-a + b)."""
    supercell = _ROCK_SALT_NIO.copy()
    supercell.make_supercell([[1, 1, 0], [-1, 1, 0], [0, 0, 1]])
    spins = iter((5.0, -5.0))
    candidate = Structure(
        supercell.lattice,
        [
            Species("Ni", spin=next(spins))
            if site.specie.symbol == "Ni"
            else site.specie
            for site in supercell
        ],
        supercell.frac_coords,
    )
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((candidate, "afm"))
    )

    state = magnetic_decision(
        _ROCK_SALT_NIO,
        is_magnetic(_ROCK_SALT_NIO),
        human=MagneticConfigHumanInput(
            magnetic_ordering="afm",
            spin_orbit_coupling=True,
            moment_direction=(0, 1, 0),
        ),
    )

    b = _ROCK_SALT_NIO.lattice.matrix[1] / np.linalg.norm(
        _ROCK_SALT_NIO.lattice.matrix[1]
    )
    labels = ("Ni1", "Ni2", "O")
    assert state.value.ordering.applied == "afm-1"
    assert state.value.angle1 == pytest.approx(
        dict.fromkeys(labels, math.degrees(math.acos(b[2])))
    )
    assert state.value.angle2 == pytest.approx(
        dict.fromkeys(labels, math.degrees(math.atan2(b[1], b[0])))
    )


_NEEDS_ENUMLIB = pytest.mark.skipif(
    _ENUMLIB_MISSING,
    reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
)


def _gdi2_monolayer(c: float = 19.94) -> Structure:
    """A 2H GdI2 sheet like MC2D's monolayer (aedf368b): Gd between two I
    planes 1.98 A away, in the xy plane of a cell ``c`` A high along z. The
    default has 15.98 A of vacuum along c; at 7 A the sheets stack into a
    bulk crystal with a 3.04 A gap, no vacuum."""
    return Structure(
        Lattice.hexagonal(4.357, c),
        ["Gd", "I", "I"],
        [[1 / 3, 2 / 3, 0.0], [2 / 3, 1 / 3, 1.98 / c], [2 / 3, 1 / 3, -1.98 / c]],
    )


def _holds(cell: Structure, vector: np.ndarray) -> bool:
    """Whether ``vector`` is a lattice vector of ``cell``."""
    fractional = cell.lattice.get_fractional_coords(vector)
    return bool(np.allclose(fractional, np.round(fractional), atol=1e-6))


def _with_gd_spins(lattice: np.ndarray, structure: Structure, shifts) -> Structure:
    """``structure`` repeated at the Cartesian ``shifts`` in a cell of
    ``lattice`` (rows), its Gd up in the first copy and down in the
    second, as the enumerator returns a candidate."""
    species, coords = [], []
    for shift, spin in zip(shifts, (5.0, -5.0), strict=True):
        for site in structure:
            species.append(
                Species("Gd", spin=spin) if site.specie.symbol == "Gd" else site.specie
            )
            coords.append(site.coords + shift)
    return Structure(Lattice(lattice), species, coords, coords_are_cartesian=True)


def _gdi2_candidates() -> dict[str, Structure]:
    """Hand-built 6-site candidates of ``_gdi2_monolayer()``: doubled
    across the vacuum (2c, moved to b as enumlib returns it), stacked across
    it with a and the next sheet up (2a, b, a + c: c is no lattice vector),
    and doubled in the sheet along b, written with -c as its second vector."""
    gdi2 = _gdi2_monolayer()
    a, b, c = gdi2.lattice.matrix
    return {
        "across": _with_gd_spins(np.array([b, 2 * c, a]), gdi2, (0 * c, c)),
        "stacked": _with_gd_spins(np.array([2 * a, b, a + c]), gdi2, (0 * a, a)),
        "in_plane": _with_gd_spins(np.array([a, -c, 2 * b]), gdi2, (0 * b, b)),
    }


def test_a_monolayer_keeps_only_orderings_whose_lattice_holds_its_vacuum_vector(
    monkeypatch,
) -> None:
    """#144: an ordering of a slab that repeats across its vacuum (2c), or
    stacks the next sheet up with a shift (a + c, c itself no lattice
    vector), puts more than one sheet in the written cell. Only the
    in-plane doubling is listed, as afm-1, and plain afm applies it."""
    gdi2 = _gdi2_monolayer()
    built = _gdi2_candidates()
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _enumerating(*((candidate, "afm") for candidate in built.values())),
    )

    candidates, warning = enumerate_magnetic_orderings(gdi2, local_moments(gdi2))
    state = magnetic_cell(gdi2, is_magnetic(gdi2), _AFM)

    assert warning is None
    assert [label for label, _cell in candidates] == ["fm", "afm-1"]
    in_plane = built["in_plane"]
    assert np.isclose(candidates[1][1].volume, in_plane.volume)
    assert _holds(candidates[1][1], 2 * gdi2.lattice.matrix[1])
    assert state.value.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=(),
    )
    framed = Resolved(framed_cell(state.value), state.provenance)
    assert magnetic_config(framed).value.compensated is True


@pytest.mark.parametrize(
    "rows",
    [("a", "-c", "2b"), ("2b", "a", "-c"), ("a+c", "2b", "c")],
    ids=["vacuum-second-and-reversed", "left-handed", "a-tilted-by-the-vacuum"],
)
def test_a_kept_ordering_is_written_with_the_input_vacuum_vector_at_its_index(
    monkeypatch, rows: tuple[str, str, str]
) -> None:
    """#144: the slab's later decisions -- vacuum axes, 'slab' isolation and
    fix_bottom_layers gates, the k-point along the vacuum, the dipole
    notice -- read the written cell. A kept candidate whose basis has -c
    second, is left-handed, or tilts a by c, is written with +c third, a
    and b in the sheet and the input's handedness, its sites where they
    were, so the cell has the input's vacuum along c."""
    gdi2 = _gdi2_monolayer()
    a, b, c = gdi2.lattice.matrix
    vectors = {"a": a, "2b": 2 * b, "c": c, "-c": -c, "a+c": a + c}
    candidate = _with_gd_spins(
        np.array([vectors[row] for row in rows]), gdi2, (0 * b, b)
    )
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((candidate, "afm"))
    )

    cell = magnetic_cell(gdi2, is_magnetic(gdi2), _AFM).value

    lattice = cell.structure.lattice.matrix
    assert np.array_equal(lattice[2], gdi2.lattice.matrix[2])
    assert np.allclose(lattice[:2, 2], 0.0)
    assert np.linalg.det(lattice) > 0
    assert np.allclose(cell.cell_in_input_basis[2], (0.0, 0.0, 1.0))
    assert vacuum_axes(cell.structure) == ("c",)
    assert slab_geometry(cell.structure) == slab_geometry(gdi2)
    assert len(slab_layers(cell.structure)) == 3


def test_afm_on_a_monolayer_with_no_ordering_in_its_sheet_keeps_ferromagnetic_order(
    monkeypatch,
) -> None:
    """#144: when every ordering found repeats across the vacuum, afm
    degrades to the ferromagnetic input with a warning saying so, and a
    label is refused with the same reason."""
    gdi2 = _gdi2_monolayer()
    built = _gdi2_candidates()
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _enumerating((built["across"], "afm"), (built["stacked"], "afm")),
    )

    fallback = magnetic_cell(gdi2, is_magnetic(gdi2), _AFM)
    refused = magnetic_cell(
        gdi2, is_magnetic(gdi2), MagneticConfigHumanInput(magnetic_ordering="afm-1")
    )

    assert _same_sites(fallback.value.structure, gdi2)
    assert fallback.value.ordering == OrderingRecord(requested="afm", applied="fm")
    [warning] = _afm_warnings(fallback.value.warnings)
    assert warning.code == "magnetic.afm_ordering_unavailable"
    assert "vacuum along c" in warning.message
    assert isinstance(refused, Blocked)
    assert "vacuum along c" in refused.root_cause()


@_NEEDS_ENUMLIB
def test_a_monolayer_lists_only_orderings_in_its_sheet() -> None:
    """#144, the GdI2 monolayer: enumlib's first candidates doubled c (moved
    to b) or stacked sheets along c + a or c + b, and plain afm applied the
    doubling, a layer-FM cell whose only antiparallel Gd sat 19.94 A away
    across the vacuum. Each listed candidate now holds the input c as its
    third vector, with a and b in the sheet, so it is one slab with the
    input's vacuum; plain afm applies the 6-site in-plane stripe."""
    gdi2 = _gdi2_monolayer()

    candidates, warning = enumerate_magnetic_orderings(gdi2, local_moments(gdi2))
    state = magnetic_cell(gdi2, is_magnetic(gdi2), _AFM)
    cell = state.value

    afm = [(label, listed) for label, listed in candidates if label != "fm"]
    assert warning is None
    assert [
        (label, len(listed), symmetry(listed).value.space_group_symbol)
        for label, listed in afm
    ] == [("afm-1", 6, "Pmm2"), ("afm-2", 12, "Pmc2_1"), ("afm-3", 12, "Pmm2")]
    for _label, listed in afm:
        assert np.array_equal(listed.lattice.matrix[2], gdi2.lattice.matrix[2])
        assert np.allclose(listed.lattice.matrix[:2, 2], 0.0)
        assert vacuum_axes(listed) == ("c",)
        assert len(slab_layers(listed)) == 3
    assert cell.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=(),
    )
    framed = Resolved(framed_cell(cell), state.provenance)
    assert magnetic_config(framed).value.compensated is True
    assert len(cell.structure) == 6
    assert np.array_equal(cell.structure.lattice.matrix[2], gdi2.lattice.matrix[2])


@_NEEDS_ENUMLIB
def test_plain_afm_applies_the_smallest_most_symmetric_and_names_the_rest() -> None:
    """#144: plain afm's criterion is stated and recorded. NiO has two
    4-site candidates: afm-1, the R-3m AFM-II cell, is applied as the most
    symmetric, and the P4/mmm one is recorded and named as its same-size
    alternative."""
    state = magnetic_cell(_ROCK_SALT_NIO, is_magnetic(_ROCK_SALT_NIO), _AFM)
    listed = dict(
        enumerate_magnetic_orderings(_ROCK_SALT_NIO, local_moments(_ROCK_SALT_NIO))[0]
    )

    assert state.value.ordering == OrderingRecord(
        requested="afm",
        applied="afm-1",
        criterion="smallest_cell",
        alternatives=("afm-2",),
    )
    assert magnetic_config(state).value.compensated is True
    for label, group in (("afm-1", "R-3m"), ("afm-2", "P4/mmm")):
        assert len(listed[label]) == 4
        assert symmetry(listed[label]).value.space_group_symbol == group
    [notice] = [
        warning
        for warning in state.value.warnings
        if warning.code == "magnetic.afm_ordering_applied"
    ]
    assert "afm-1" in notice.message
    assert "smallest" in notice.message
    assert "afm-2" in notice.message


@_NEEDS_ENUMLIB
def test_a_bulk_layered_magnet_keeps_its_interlayer_orderings() -> None:
    """#144 filters on vacuum, not on the '2d' rank: GdI2 sheets stacked
    3.04 A apart have no vacuum, so orderings across the stacking, such as
    the doubling along c, are listed as before."""
    bulk = _gdi2_monolayer(c=7.0)

    candidates, _warning = enumerate_magnetic_orderings(bulk, local_moments(bulk))

    first = dict(candidates)["afm-1"]
    assert vacuum_axes(bulk) == ()
    assert len(first) == 6
    assert symmetry(first).value.space_group_symbol == "P-6m2"
    assert not _holds(first, bulk.lattice.matrix[2])
    assert _holds(first, 2 * bulk.lattice.matrix[2])


def _mno_chain() -> Structure:
    """A Mn-O-Mn chain along a, 4.44 A per MnO, in a cell with 14 A of
    vacuum along b and c: a wire."""
    return Structure(
        Lattice.orthorhombic(4.44, 14.0, 14.0),
        ["Mn", "O"],
        [[0.0, 0.5, 0.5], [0.5, 0.5, 0.5]],
    )


def _fe2o2_molecule() -> Structure:
    """A planar Fe2O2 rhombus (Fe-O 1.92 A) in a 12 A box: vacuum along a,
    b and c, a molecule."""
    return Structure(
        Lattice.cubic(12.0),
        ["Fe", "O", "Fe", "O"],
        [[0.42, 0.42, 0.5], [0.58, 0.42, 0.5], [0.58, 0.58, 0.5], [0.42, 0.58, 0.5]],
    )


def _with_spins(
    lattice: np.ndarray, structure: Structure, element: str, shifts
) -> Structure:
    """``structure`` repeated at the Cartesian ``shifts`` in a cell of
    ``lattice`` (rows), its ``element`` up in the first copy and down in
    the second, as the enumerator returns a candidate."""
    species, coords = [], []
    for shift, spin in zip(shifts, (5.0, -5.0), strict=True):
        for site in structure:
            species.append(
                Species(element, spin=spin)
                if site.specie.symbol == element
                else site.specie
            )
            coords.append(site.coords + shift)
    return Structure(Lattice(lattice), species, coords, coords_are_cartesian=True)


def _alternating_spins(
    lattice: np.ndarray, structure: Structure, element: str
) -> Structure:
    """``structure``'s sites in a cell of ``lattice`` (rows), its
    ``element`` sites up and down in turn."""
    spins = iter((5.0, -5.0) * len(structure))
    species = [
        Species(element, spin=next(spins))
        if site.specie.symbol == element
        else site.specie
        for site in structure
    ]
    return Structure(
        Lattice(lattice), species, structure.cart_coords, coords_are_cartesian=True
    )


@pytest.mark.parametrize(
    "rows",
    [("2a", "b", "c"), ("c", "2a", "-b"), ("2a+b+c", "b+c", "c")],
    ids=["as-input", "vacuum-vectors-moved-and-reversed", "tilted-by-the-vacuum"],
)
def test_a_wire_ordering_is_written_with_both_vacuum_vectors_at_their_indices(
    monkeypatch, rows: tuple[str, str, str]
) -> None:
    """#144, two vacuum axes: a wire's ordering along its axis is kept and
    written with the input b and c as its second and third vectors and the
    doubled chain axis perpendicular to them, whichever basis of its
    lattice the enumerator returned."""
    chain = _mno_chain()
    a, b, c = chain.lattice.matrix
    vectors = {
        "2a": 2 * a,
        "b": b,
        "c": c,
        "-b": -b,
        "2a+b+c": 2 * a + b + c,
        "b+c": b + c,
    }
    candidate = _with_spins(
        np.array([vectors[row] for row in rows]), chain, "Mn", (0 * a, a)
    )
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((candidate, "afm"))
    )

    cell = magnetic_cell(chain, is_magnetic(chain), _AFM).value

    lattice = cell.structure.lattice.matrix
    assert cell.ordering.applied == "afm-1"
    assert np.array_equal(lattice[1:], chain.lattice.matrix[1:])
    assert np.allclose(lattice[0], 2 * a)
    assert np.allclose(cell.cell_in_input_basis, np.diag((2.0, 1.0, 1.0)))
    assert vacuum_axes(cell.structure) == ("b", "c")
    assert _spins(cell.structure, "Mn") == {1.0, -1.0}


def test_a_molecule_keeps_only_orderings_of_its_own_box(monkeypatch) -> None:
    """#144, three vacuum axes: an ordering of a boxed molecule that
    doubles the box puts two molecules in the written cell. Only the
    ordering inside the box is listed, written in the input's own cell
    even when the enumerator returns that lattice in another basis."""
    molecule = _fe2o2_molecule()
    a, b, c = molecule.lattice.matrix
    inside = _alternating_spins(np.array([b, -c, a]), molecule, "Fe")
    doubled = _with_spins(np.array([2 * a, b, c]), molecule, "Fe", (0 * a, a))
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module,
        "enumerate_orderings",
        _enumerating((doubled, "afm"), (inside, "afm")),
    )

    candidates, warning = enumerate_magnetic_orderings(
        molecule, local_moments(molecule)
    )
    cell = magnetic_cell(molecule, is_magnetic(molecule), _AFM).value

    assert warning is None
    assert [label for label, _listed in candidates] == ["fm", "afm-1"]
    assert np.array_equal(candidates[1][1].lattice.matrix, molecule.lattice.matrix)
    assert cell.ordering.applied == "afm-1"
    assert np.array_equal(cell.structure.lattice.matrix, molecule.lattice.matrix)
    assert np.allclose(cell.cell_in_input_basis, np.eye(3))
    assert _spins(cell.structure, "Fe") == {1.0, -1.0}


def test_a_molecule_whose_every_ordering_doubles_its_box_is_refused_an_afm_label(
    monkeypatch,
) -> None:
    molecule = _fe2o2_molecule()
    a, b, c = molecule.lattice.matrix
    doubled = _with_spins(np.array([2 * a, b, c]), molecule, "Fe", (0 * a, a))
    monkeypatch.setattr(shutil, "which", _on_path("enum.x", "makeStr.py"))
    monkeypatch.setattr(
        magnetic_config_module, "enumerate_orderings", _enumerating((doubled, "afm"))
    )

    fallback = magnetic_cell(molecule, is_magnetic(molecule), _AFM)
    refused = magnetic_cell(
        molecule,
        is_magnetic(molecule),
        MagneticConfigHumanInput(magnetic_ordering="afm-1"),
    )

    assert _same_sites(fallback.value.structure, molecule)
    assert fallback.value.ordering == OrderingRecord(requested="afm", applied="fm")
    assert isinstance(refused, Blocked)
    assert "vacuum along a and b and c" in refused.root_cause()


@_NEEDS_ENUMLIB
def test_a_wire_lists_only_orderings_along_its_axis() -> None:
    """#144 with real enumlib: every listed ordering of a MnO chain keeps
    the input b and c, so each is one wire with the input's vacuum, and
    plain afm applies the 4-site doubling along the chain."""
    chain = _mno_chain()

    candidates, warning = enumerate_magnetic_orderings(chain, local_moments(chain))
    cell = magnetic_cell(chain, is_magnetic(chain), _AFM).value

    afm = [(label, listed) for label, listed in candidates if label != "fm"]
    assert warning is None
    assert afm
    for _label, listed in afm:
        assert np.array_equal(listed.lattice.matrix[1:], chain.lattice.matrix[1:])
        assert vacuum_axes(listed) == ("b", "c")
    assert cell.ordering.applied == "afm-1"
    assert len(cell.structure) == 4
    assert np.allclose(cell.structure.lattice.matrix[0], 2 * chain.lattice.matrix[0])
    assert np.array_equal(cell.structure.lattice.matrix[1:], chain.lattice.matrix[1:])


@_NEEDS_ENUMLIB
def test_a_molecule_in_a_box_keeps_its_cell() -> None:
    """#144 with real enumlib: the Fe2O2 molecule's only listed ordering is
    the input cell, Fe up and down, and plain afm applies it."""
    molecule = _fe2o2_molecule()

    candidates, warning = enumerate_magnetic_orderings(
        molecule, local_moments(molecule)
    )
    cell = magnetic_cell(molecule, is_magnetic(molecule), _AFM).value

    assert warning is None
    assert [label for label, _listed in candidates] == ["fm", "afm-1"]
    assert np.array_equal(candidates[1][1].lattice.matrix, molecule.lattice.matrix)
    assert cell.ordering.applied == "afm-1"
    assert len(cell.structure) == 4
    assert np.array_equal(cell.structure.lattice.matrix, molecule.lattice.matrix)
    assert _spins(cell.structure, "Fe") == {1.0, -1.0}


def _non_magnetic_cell(structure: Structure):
    return magnetic_cell(
        structure, Resolved("non_magnetic", Provenance(source="heuristic"))
    ).value


def _frame_notices(cell) -> list[str]:
    return [
        warning.message
        for warning in cell.warnings
        if warning.code == "magnetic.cell_framed"
    ]


@pytest.mark.parametrize(("lift", "noticed"), [(4e-4, True), (1e-4, False)])
def test_the_frame_notice_starts_at_a_tenth_of_a_milliangstrom(
    lift: float, noticed: bool
) -> None:
    """#140: idealizing a MoS2 sheet whose top S is lifted moves both S
    atoms by half the lift. CIF rounding moves atoms by about 1e-5 A, so a
    notice on every movement would fire on almost every run; one at 1e-4 A
    or more names it."""
    sheet = molybdenum_disulfide_monolayer()
    lifted = sheet.frac_coords + np.array([[0, 0, 0], [0, 0, lift / 20.0], [0, 0, 0]])

    cell = framed_cell(
        _non_magnetic_cell(Structure(sheet.lattice, sheet.species, lifted))
    )

    assert cell.frame.max_displacement_angstrom == pytest.approx(lift / 2, abs=1e-6)
    assert not cell.frame.rotated
    assert bool(_frame_notices(cell)) is noticed


def test_an_origin_shift_is_noticed_without_a_rotation() -> None:
    """#140: a MoS2 sheet with its Mo mirror at fractional z = 0.37 is written
    with the mirror at 1/2; every written coordinate moves by the shift, so
    the notice names it, and only a turned cell refuses Cartesian
    cell_dofree masks."""
    sheet = molybdenum_disulfide_monolayer()
    off_centre = Structure(
        sheet.lattice, sheet.species, sheet.frac_coords + np.array([0, 0, -0.13])
    )

    cell = framed_cell(_non_magnetic_cell(off_centre))

    (notice,) = _frame_notices(cell)
    assert notice.startswith(
        "the cell is written with its origin moved by [0, 0, 0.13] (crystal "
        "coordinates); pw.x"
    )
    assert "keeps 12 symmetry operations" in notice
    assert "cell_dofree" not in notice
