from __future__ import annotations

import dataclasses
from typing import get_args

import pytest
from pydantic import ValidationError
from support import geometry_facts

from goldilocks_core.advisors.convergence import ConvergenceHumanInput, convergence
from goldilocks_core.advisors.relax import (
    CellDofree,
    RelaxHumanInput,
    RelaxLlmInput,
    RelaxOptions,
    RelaxProtocol,
    VcRelaxOptions,
    relax_settings,
)
from goldilocks_core.resolution import (
    Blocked,
    Provenance,
    Resolved,
    Unavailable,
    Warning,
)

_CONVERGENCE = convergence(nat=4)
_IBRAV_0_CELL_DOFREE = {
    "all",
    "shape",
    "a",
    "b",
    "c",
    "fixa",
    "fixb",
    "fixc",
    "x",
    "y",
    "z",
    "xy",
    "xz",
    "yz",
    "xyz",
    "2Dxy",
    "2Dshape",
    "epitaxial_ab",
    "epitaxial_ac",
    "epitaxial_bc",
}
"""QE 7.3 ``init_dofree``'s (Modules/cell_base.f90:710-830) values that do
what they name under the ``ibrav = 0`` the writer always emits."""


def _geometry(dimensionality: str, vacuum_axes=(), *, ab_in_xy: bool = True):
    facts = geometry_facts(dimensionality, vacuum_axes, ab_in_xy=ab_in_xy)
    return Resolved(facts, Provenance(source="heuristic"))


def _vc_relax(geometry, **overrides):
    return relax_settings("vc-relax", _CONVERGENCE, geometry=geometry, **overrides)


def test_plain_relax_uses_qe_defaults() -> None:
    state = relax_settings("relax", _CONVERGENCE)

    assert state.ok
    assert type(state.value) is RelaxOptions
    assert state.value.ion_dynamics == "bfgs"
    assert state.value.forc_conv_thr == 1.0e-3
    assert state.value.nstep == 50
    assert state.value.trust_radius_max == 0.8
    assert state.value.trust_radius_min == 1.0e-3
    assert state.value.trust_radius_ini == 0.5
    assert state.value.remove_rigid_rot is False
    assert state.source == "heuristic"


def test_etot_conv_thr_is_inherited_from_convergence_not_recomputed() -> None:
    tight_convergence = convergence(nat=200)

    state = relax_settings("relax", tight_convergence)

    assert state.value.etot_conv_thr == tight_convergence.value.etot_conv_thr
    assert state.value.etot_conv_thr == 0.002


def test_blocked_convergence_blocks_relax_settings() -> None:
    state = relax_settings("relax", Blocked(by="functional undecided"))

    assert isinstance(state, Blocked)
    assert state.root_cause() == "functional undecided"


def test_unavailable_convergence_blocks_relax_settings() -> None:
    state = relax_settings("relax", Unavailable(reason="synthetic"))

    assert isinstance(state, Blocked)
    assert state.root_cause() == "synthetic"


def test_vc_relax_returns_vc_relax_options_with_its_own_defaults() -> None:
    state = relax_settings("vc-relax", _CONVERGENCE)

    assert type(state.value) is VcRelaxOptions
    assert state.value.cell_dofree == "all"
    assert state.value.press == 0.0
    assert state.value.press_conv_thr == 0.5
    assert state.value.cell_factor == 2.0


def test_cell_dofree_offers_only_values_pw_x_honours_under_ibrav_0() -> None:
    """#153: under the writer's ibrav = 0, 'volume' stops pw.x ("Isotropic
    expansion is only allowed for ibrav=1", Modules/cell_base.f90:751-756)
    and every 'ibrav' form only prints that it has no effect
    (Modules/latgen.f90:749-752)."""
    assert set(get_args(CellDofree)) == _IBRAV_0_CELL_DOFREE


@pytest.mark.parametrize("bag", [RelaxHumanInput, RelaxLlmInput])
@pytest.mark.parametrize("value", ["volume", "ibrav", "ibrav+volume", "ibrav+2Dxy"])
def test_a_cell_dofree_ibrav_0_cannot_honour_is_refused(bag, value: str) -> None:
    with pytest.raises(ValidationError, match="cell_dofree"):
        bag(cell_dofree=value)


def test_vc_relax_options_cell_dynamics_mirrors_ion_dynamics() -> None:
    state = relax_settings(
        "vc-relax", _CONVERGENCE, human=RelaxHumanInput(ion_dynamics="damp")
    )

    assert state.value.ion_dynamics == "damp"
    assert state.value.cell_dynamics == "damp"


def test_human_can_override_ion_dynamics_and_stays_human_sourced() -> None:
    state = relax_settings(
        "relax", _CONVERGENCE, human=RelaxHumanInput(ion_dynamics="fire")
    )

    assert state.value.ion_dynamics == "fire"
    assert state.source == "human"


def test_human_can_override_a_single_field_others_keep_their_default() -> None:
    state = relax_settings("relax", _CONVERGENCE, human=RelaxHumanInput(nstep=200))

    assert state.value.nstep == 200
    assert state.value.forc_conv_thr == 1.0e-3
    assert state.source == "human"


def test_llm_can_adjust_ion_dynamics_but_source_reflects_llm() -> None:
    state = relax_settings(
        "relax", _CONVERGENCE, llm=RelaxLlmInput(ion_dynamics="damp")
    )

    assert state.value.ion_dynamics == "damp"
    assert state.source == "llm"


def test_no_overrides_gives_heuristic_source() -> None:
    state = relax_settings("relax", _CONVERGENCE)

    assert state.source == "heuristic"


def test_fix_bottom_layers_defaults_to_none() -> None:
    state = relax_settings("relax", _CONVERGENCE)

    assert state.value.fix_bottom_layers is None


def test_human_can_set_fix_bottom_layers_and_it_is_human_sourced() -> None:
    state = relax_settings(
        "relax", _CONVERGENCE, human=RelaxHumanInput(fix_bottom_layers=2)
    )

    assert state.value.fix_bottom_layers == 2
    assert state.source == "human"


def test_fix_bottom_layers_has_no_llm_counterpart() -> None:
    """Human-only, unlike ``ion_dynamics``/``nstep`` -- ``RelaxLlmInput``
    does not even have this field, so there is nothing an llm tier can
    set here (a structural decision, not a scenario choice)."""
    assert not hasattr(RelaxLlmInput(), "fix_bottom_layers")


def test_a_layered_rank_without_vacuum_relaxes_the_whole_cell() -> None:
    """#132: bulk graphite ranks '2d' but has no vacuum; '2Dxy' froze its
    stacking axis on SCARF."""
    state = _vc_relax(_geometry("2d"))

    assert state.value.cell_dofree == "all"
    assert state.value.warnings == ()
    assert state.provenance.field_sources["cell_dofree"] == "heuristic"


def test_a_slab_in_the_xy_frame_holds_its_vacuum_fixed() -> None:
    state = _vc_relax(_geometry("2d", ("c",)))

    assert state.value.cell_dofree == "2Dxy"
    assert state.value.warnings == ()
    assert state.provenance.field_sources["cell_dofree"] == "heuristic"


def test_a_slab_with_its_vacuum_along_a_is_blocked() -> None:
    state = _vc_relax(_geometry("2d", ("a",)))

    assert isinstance(state, Blocked)
    assert "cell_dofree" in state.root_cause()
    assert "vacuum along a" in state.root_cause()
    assert "Reorient the cell" in state.root_cause()


def test_a_slab_with_a_and_b_out_of_the_xy_plane_is_blocked() -> None:
    state = _vc_relax(_geometry("2d", ("c",), ab_in_xy=False))

    assert isinstance(state, Blocked)
    assert "cell_dofree" in state.root_cause()
    assert "a or b out of the xy plane" in state.root_cause()


@pytest.mark.parametrize(
    ("vacuum_axes", "suggestion"),
    [
        (
            ("a", "b"),
            "cell_dofree='epitaxial_ab' holds a and b fixed and relaxes only c,",
        ),
        (
            ("a", "c"),
            "cell_dofree='epitaxial_ac' holds a and c fixed and relaxes only b,",
        ),
        (
            ("b", "c"),
            "cell_dofree='epitaxial_bc' holds b and c fixed and relaxes only a,",
        ),
    ],
)
def test_a_wire_is_blocked_with_the_constraint_on_its_period(
    vacuum_axes: tuple[str, str], suggestion: str
) -> None:
    """QE's epitaxial constraints move every component of one lattice vector
    and hold the other two (QE 7.3 Modules/cell_base.f90:825-842), so they
    relax a wire's period and hold its vacuum in any orientation, where 'x',
    'y' or 'z' would move one Cartesian component of the period."""
    state = _vc_relax(_geometry("1d", vacuum_axes))

    assert isinstance(state, Blocked)
    assert f"vacuum along {' and '.join(vacuum_axes)}" in state.root_cause()
    assert suggestion in state.root_cause()


def test_vacuum_along_every_axis_relaxes_the_whole_cell() -> None:
    """The Martyna-Tuckerman boundary gate refuses this vc-relax once,
    with remedies that do not involve cell_dofree."""
    state = _vc_relax(_geometry("molecule", ("a", "b", "c")))

    assert state.value.cell_dofree == "all"


def test_missing_or_unresolved_geometry_falls_back_to_cell_dofree_all() -> None:
    assert _vc_relax(None).value.cell_dofree == "all"
    assert _vc_relax(Unavailable(reason="disordered")).value.cell_dofree == "all"


def test_a_plain_relax_of_a_wire_is_not_blocked() -> None:
    state = relax_settings("relax", _CONVERGENCE, geometry=_geometry("1d", ("a", "b")))

    assert type(state.value) is RelaxOptions


def test_a_human_cell_dofree_on_a_slab_outside_the_frame_is_kept() -> None:
    state = _vc_relax(
        _geometry("2d", ("a",)), human=RelaxHumanInput(cell_dofree="shape")
    )

    assert state.value.cell_dofree == "shape"
    assert state.value.warnings == ()
    assert state.provenance.field_sources["cell_dofree"] == "human"


def test_an_llm_cell_dofree_on_a_wire_is_kept() -> None:
    state = _vc_relax(_geometry("1d", ("a", "b")), llm=RelaxLlmInput(cell_dofree="z"))

    assert state.value.cell_dofree == "z"
    assert state.provenance.field_sources["cell_dofree"] == "llm"


def test_a_vc_relax_key_on_a_relax_is_not_the_request_s() -> None:
    """#173: a relax applies no press, so a human press leaves the record
    heuristic instead of labelling it 'human' (#154)."""
    state = relax_settings("relax", _CONVERGENCE, human=RelaxHumanInput(press=5.0))

    assert not hasattr(state.value, "press")
    assert state.source == "heuristic"
    assert "press" not in state.provenance.field_sources


def test_every_applied_relax_field_reads_the_tier_that_set_it() -> None:
    convergence_state = convergence(
        nat=4, human=ConvergenceHumanInput(etot_conv_thr=1e-6)
    )

    state = relax_settings(
        "vc-relax",
        convergence_state,
        geometry=_geometry("3d"),
        human=RelaxHumanInput(press=5.0, forc_conv_thr=1e-4),
        llm=RelaxLlmInput(nstep=80, press=1.0),
    )

    assert state.source == "human"
    assert state.provenance.field_sources == {
        "ion_dynamics": "heuristic",
        "forc_conv_thr": "human",
        "etot_conv_thr": "human",
        "nstep": "llm",
        "trust_radius_max": "heuristic",
        "trust_radius_min": "heuristic",
        "trust_radius_ini": "heuristic",
        "remove_rigid_rot": "heuristic",
        "fix_bottom_layers": "heuristic",
        "cell_dofree": "heuristic",
        "press": "human",
        "press_conv_thr": "heuristic",
        "cell_factor": "heuristic",
    }


_PROTOCOL = RelaxProtocol(
    forc_conv_thr=1.0e-4,
    note="A task protocol's force threshold.",
    citations=("Protocol citation.",),
    loose_warning=Warning(
        code="relax.protocol_threshold_loosened",
        level="warning",
        category="relax",
        message="forc_conv_thr is looser than the task's 1e-4 Ry/Bohr.",
    ),
)
"""A stand-in for a task's relaxation protocol, such as the phonon tasks'
1e-4 Ry/Bohr (#215)."""


def test_without_a_protocol_forc_conv_thr_is_the_qe_default_with_no_note() -> None:
    state = relax_settings("relax", _CONVERGENCE)

    assert state.value.forc_conv_thr == 1.0e-3
    assert state.provenance.source_note is None
    assert state.provenance.citations == ()


def test_a_protocol_sets_forc_conv_thr_and_names_itself() -> None:
    """#215: the protocol's 1e-4 Ry/Bohr is not a request value, so the record
    reads heuristic, with the protocol's note and citations."""
    state = relax_settings("relax", _CONVERGENCE, protocol=_PROTOCOL)

    assert state.value.forc_conv_thr == 1.0e-4
    assert state.value.warnings == ()
    assert state.source == "heuristic"
    assert state.provenance.field_sources["forc_conv_thr"] == "heuristic"
    assert state.provenance.source_note == "A task protocol's force threshold."
    assert state.provenance.citations == ("Protocol citation.",)


def test_a_protocol_on_a_vc_relax_sets_only_forc_conv_thr() -> None:
    state = _vc_relax(_geometry("3d"), protocol=_PROTOCOL)

    plain = _vc_relax(_geometry("3d"))
    assert state.value == dataclasses.replace(plain.value, forc_conv_thr=1.0e-4)
    assert (
        state.value.cell_dofree,
        state.value.press_conv_thr,
        state.value.cell_factor,
    ) == ("all", 0.5, 2.0)
    assert state.provenance.field_sources == plain.provenance.field_sources
    assert state.provenance.source_note == "A task protocol's force threshold."


@pytest.mark.parametrize(
    ("forc_conv_thr", "warnings"),
    [(5.0e-4, (_PROTOCOL.loose_warning,)), (1.0e-4, ()), (5.0e-5, ())],
    ids=["looser", "equal", "tighter"],
)
def test_a_request_forc_conv_thr_wins_over_the_protocol(
    forc_conv_thr: float, warnings: tuple[Warning, ...]
) -> None:
    """#215: a request value is used as given and reads human, without the
    protocol's note; only one looser than the protocol's carries its
    warning."""
    state = relax_settings(
        "relax",
        _CONVERGENCE,
        human=RelaxHumanInput(forc_conv_thr=forc_conv_thr),
        protocol=_PROTOCOL,
    )

    assert state.value.forc_conv_thr == forc_conv_thr
    assert state.value.warnings == warnings
    assert state.source == "human"
    assert state.provenance.field_sources["forc_conv_thr"] == "human"
    assert state.provenance.source_note is None
    assert state.provenance.citations == ()


def test_a_loose_request_without_a_protocol_carries_no_warning() -> None:
    state = relax_settings(
        "relax", _CONVERGENCE, human=RelaxHumanInput(forc_conv_thr=5.0e-4)
    )

    assert state.value.forc_conv_thr == 5.0e-4
    assert state.value.warnings == ()
