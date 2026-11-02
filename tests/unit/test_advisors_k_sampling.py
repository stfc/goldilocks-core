from __future__ import annotations

import math

import numpy as np
import pytest
from pymatgen.core import Element, Lattice, Structure
from support import (
    alpha_uranium,
    carbon_pair_in_a_box,
    graphene_monolayer,
    uranium_nitride,
    written_bcc_iron,
    written_silicon,
    written_sodium_chloride,
)

from goldilocks_core.advisors.k_sampling import (
    KSamplingHumanInput,
    KSamplingLlmInput,
    KSamplingProtocol,
    PhononKProtocol,
    k_sampling,
)
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.q_sampling import QSamplingHumanInput
from goldilocks_core.advisors.species_split import split_species
from goldilocks_core.analysis.is_metal import is_metal
from goldilocks_core.kmesh import build_gamma_kmesh_entries, k_distance_to_mesh
from goldilocks_core.ml import predict as predict_module
from goldilocks_core.ml.predict import MlPrediction
from goldilocks_core.resolution import (
    Blocked,
    ModelEvidence,
    Provenance,
    Resolved,
    Unavailable,
)

_IRON = Structure(Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]])
_SILICON = Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])
_BCC_IRON = Structure.from_spacegroup(
    "Im-3m", Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]]
)
_NON_METAL = Resolved("non_metal", Provenance(source="heuristic"))


def test_metal_gets_the_denser_default_k_distance() -> None:
    state = k_sampling(is_metal(_IRON), _IRON)

    assert state.ok
    assert state.value.k_distance == 0.15
    assert state.value.mesh == k_distance_to_mesh(_IRON, 0.15)
    assert state.value.shift == (0, 0, 0)


def test_human_shift_applies_on_the_pure_heuristic_default_path() -> None:
    """Regression for #34 (v2 epic 9, #9): a human-supplied shift with no
    matching k_grid/k_distance override used to be silently dropped in
    the pure-heuristic branches -- K_POINTS was always Gamma-centered
    regardless of the requested shift."""
    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(shift=(1, 1, 1))
    )

    assert state.ok
    assert state.value.shift == (1, 1, 1)
    assert state.value.k_distance == 0.15


def test_confirmed_non_metal_gets_the_coarser_default_k_distance() -> None:
    state = k_sampling(Resolved("non_metal", Provenance(source="heuristic")), _SILICON)

    assert state.value.k_distance == 0.30
    assert state.value.mesh == k_distance_to_mesh(_SILICON, 0.30)


def test_unavailable_metallicity_leans_toward_the_metal_default() -> None:
    """Unlike occupations.py, uncertain metallicity here leans toward the
    denser (metal) k_distance -- an under-sampled undetected metal risks
    a silently wrong answer, an over-sampled insulator only costs more."""
    state = k_sampling(
        Unavailable(reason="composition alone does not confirm"), _SILICON
    )

    assert state.ok
    assert state.value.k_distance == 0.15


def test_blocked_metallicity_propagates_as_blocked() -> None:
    state = k_sampling(Blocked(by="synthetic failure"), _IRON)

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_human_k_grid_wins_outright() -> None:
    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_grid=(4, 4, 4))
    )

    assert state.value.mesh == (4, 4, 4)
    assert state.value.k_distance is None
    assert state.source == "human"


def test_human_k_grid_with_a_shift() -> None:
    state = k_sampling(
        is_metal(_IRON),
        _IRON,
        human=KSamplingHumanInput(k_grid=(4, 4, 4), shift=(1, 1, 1)),
    )

    assert state.value.shift == (1, 1, 1)


def test_human_k_grid_and_k_distance_together_warns_and_grid_wins() -> None:
    state = k_sampling(
        is_metal(_IRON),
        _IRON,
        human=KSamplingHumanInput(k_grid=(4, 4, 4), k_distance=0.2),
    )

    assert state.value.mesh == (4, 4, 4)
    assert any("k_grid wins" in warning.message for warning in state.value.warnings)


def test_human_k_distance_without_a_grid_is_converted_to_a_mesh() -> None:
    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_distance=0.25)
    )

    assert state.value.mesh == k_distance_to_mesh(_IRON, 0.25)
    assert state.value.k_distance == 0.25
    assert state.source == "human"


def test_llm_k_distance_is_honored_when_no_human_override_exists() -> None:
    state = k_sampling(is_metal(_IRON), _IRON, llm=KSamplingLlmInput(k_distance=0.2))

    assert state.value.k_distance == 0.2
    assert state.source == "llm"


def test_ml_k_distance_used_when_qrf95_is_installed_and_no_override(
    real_assets,
) -> None:
    """v2 epic 11 (#11) follow-up, #92: QRF95's own PSDI record always
    carried a real model.json, it just was never registered as one of
    ``[defaults.kpoints]``'s asset files -- this exercises the actual,
    installed model, not a monkeypatched stand-in."""
    state = k_sampling(is_metal(_IRON), _IRON)

    assert state.ok
    assert state.source == "ml"
    assert state.value.k_distance is not None
    assert state.value.mesh == k_distance_to_mesh(_IRON, state.value.k_distance)
    assert state.value.shift == (0, 0, 0)


def test_ml_k_distance_respects_a_human_shift(real_assets) -> None:
    """Regression for the same class of bug as #34 (see the pure
    -heuristic-path regression above): the ml branch used to hardcode
    ``shift=None`` regardless of what the human asked for."""
    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(shift=(1, 1, 1))
    )

    assert state.provenance.field_sources == {"k_distance": "ml", "shift": "human"}
    assert state.value.shift == (1, 1, 1)


def test_human_k_distance_wins_over_ml(real_assets) -> None:
    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_distance=0.25)
    )

    assert state.source == "human"
    assert state.value.k_distance == 0.25


def _afm_nickel_oxide() -> Structure:
    """Conventional rock-salt NiO split as the magnetic step splits it:
    Ni up at z = 0 and down at z = 1/2, O unspun (``split_species``)."""
    nio = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    classes = [
        (1.0 if site.frac_coords[2] < 0.25 else -1.0)
        if site.specie.symbol == "Ni"
        else 0.0
        for site in nio
    ]
    return split_species(nio, classes)


def test_the_ml_tier_reads_a_spin_split_cell_as_plain_elements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#170: a spin-polarized cell's species carry their
    starting-magnetization class as ``Species.spin``, which QRF95 was not
    trained on. The model gets the same lattice and sites as plain
    elements."""
    read: list[Structure] = []
    prediction = MlPrediction(
        value=0.25,
        provenance=Provenance(
            source="ml",
            model=ModelEvidence(
                model_id="k_points.k_distance.qrf@comp_struct_soap_lattice_metal.v1",
                asset="models/qrf-kpoints@QRF95",
                target_contract="goldilocks.k_distance.mesh_lower_bound.2pi.v1",
                value=0.25,
                details={"interval": [0.18, 0.45]},
            ),
        ),
    )

    def predict(structure: Structure) -> MlPrediction:
        read.append(structure)
        return prediction

    monkeypatch.setattr(predict_module, "predict_k_distance", predict)
    cell = _afm_nickel_oxide()

    state = k_sampling(_NON_METAL, cell)

    assert state.provenance == Provenance(
        source="ml",
        field_sources={"k_distance": "ml", "shift": "heuristic"},
        model=prediction.provenance.model,
    )
    [model_input] = read
    assert all(isinstance(site.specie, Element) for site in model_input)
    assert [site.specie.symbol for site in model_input] == [
        site.specie.symbol for site in cell
    ]
    assert np.allclose(model_input.lattice.matrix, cell.lattice.matrix)
    assert np.allclose(model_input.frac_coords, cell.frac_coords)


def test_an_afm_split_cell_gets_the_k_distance_of_its_bare_cell(real_assets) -> None:
    """#170: QRF95 predicted 0.262 1/A for this AFM NiO cell with its spin
    classes and 0.266 without (LiFePO4's afm-1 moved by 11%), so an AFM
    deck was meshed differently from the same cell's FM one."""
    cell = _afm_nickel_oxide()

    split = k_sampling(_NON_METAL, cell)
    bare = k_sampling(_NON_METAL, split_species(cell, None))

    assert split.source == bare.source == "ml"
    assert split.value.k_distance == bare.value.k_distance


def test_human_k_index_resolves_to_that_rung_s_own_mesh() -> None:
    entries = build_gamma_kmesh_entries(_IRON)

    state = k_sampling(is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_index=3))

    assert state.ok
    assert state.value.mesh == entries[2].mesh
    assert state.value.k_distance is None
    assert state.value.k_index == 3
    assert state.value.k_distance_interval == entries[2].k_distance_interval
    assert state.source == "human"


def test_heuristic_default_k_index_matches_the_ladder() -> None:
    """Not every resolved mesh lands on a rung -- this cross-checks
    whatever `k_index` the heuristic path attached against an
    independently built ladder, rather than assuming 0.15 A^-1 happens to
    land on one for this particular fixture (it may not)."""
    state = k_sampling(is_metal(_IRON), _IRON)

    entries = build_gamma_kmesh_entries(_IRON)
    expected = next(
        (entry.kindex for entry in entries if entry.mesh == state.value.mesh), None
    )
    assert state.value.k_index == expected


def test_human_k_distance_landing_on_a_rung_reverse_derives_k_index() -> None:
    entries = build_gamma_kmesh_entries(_IRON)
    third_rung = entries[2]
    low, high = third_rung.k_distance_interval
    midpoint = (low + high) / 2

    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_distance=midpoint)
    )

    assert state.ok
    assert state.value.mesh == third_rung.mesh
    assert state.value.k_index == 3
    assert state.value.k_distance_interval == third_rung.k_distance_interval


def test_human_k_grid_matching_a_ladder_rung_reverse_derives_k_index() -> None:
    entries = build_gamma_kmesh_entries(_IRON)
    third_rung_mesh = entries[2].mesh

    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_grid=third_rung_mesh)
    )

    assert state.ok
    assert state.value.k_index == 3
    assert state.value.k_distance_interval == entries[2].k_distance_interval


def test_human_k_grid_off_the_ladder_leaves_k_index_none() -> None:
    """Iron is cubic, so its ladder only ever contains (n, n, n) meshes --
    an anisotropic grid can never land on a rung."""
    state = k_sampling(
        is_metal(_IRON), _IRON, human=KSamplingHumanInput(k_grid=(1, 2, 1))
    )

    assert state.ok
    assert state.value.mesh == (1, 2, 1)
    assert state.value.k_index is None
    assert state.value.k_distance_interval is None


@pytest.mark.parametrize(
    "human",
    [KSamplingHumanInput(k_grid=(1, 1, 1)), KSamplingHumanInput(k_index=1)],
    ids=["k_grid", "k_index"],
)
def test_gamma_only_mesh_has_an_open_k_distance_interval(
    human: KSamplingHumanInput,
) -> None:
    """The Gamma-only mesh is rung 1, which every k-distance above the
    largest reciprocal length |b| = 2 pi / a gives, so its interval has
    no upper bound: None, never inf, which no strict JSON surface can
    carry (#137)."""
    state = k_sampling(is_metal(_BCC_IRON), _BCC_IRON, human=human)

    assert state.ok
    assert state.value.mesh == (1, 1, 1)
    assert state.value.k_index == 1
    assert state.value.k_distance_interval == (round(2 * math.pi / 2.87, 8), None)


def test_a_k_index_on_a_noisy_cubic_cell_names_its_cubic_mesh() -> None:
    """#163: on UN as Materials Project serves it (mp-1865), whose three
    reciprocal lengths differ in the seventh significant figure, k_index=33
    gave 32x33x32 (8721 irreducible k-points, its neighbours 897 and 969)
    with an interval 1e-8 A^-1 wide. Rung n is now n x n x n, and its
    interval runs between rungs 34 and 32."""
    structure = uranium_nitride()

    state = k_sampling(_NON_METAL, structure, human=KSamplingHumanInput(k_index=33))

    entries = build_gamma_kmesh_entries(structure)
    assert state.value.mesh == (33, 33, 33)
    assert state.value.k_index == 33
    assert state.value.k_distance_interval == (0.06761454, 0.0697275)
    assert state.value.k_distance_interval == (
        entries[33].k_distance_interval[1],
        entries[31].k_distance_interval[0],
    )


def test_the_heuristic_mesh_of_alpha_uranium_is_invariant_and_on_a_rung() -> None:
    """#163: the metal default 0.15 A^-1 meshed alpha-U (Materials Project
    mp-44, whose point group mixes a and b) as 17x15x9, a mesh the point
    group does not keep. a and b now share the denser count, and the
    reverse lookup finds the mesh on the ladder: rung 25, which holds from
    0.1476 to 0.1568 A^-1."""
    structure = alpha_uranium()

    state = k_sampling(is_metal(structure), structure)

    assert state.source == "heuristic"
    assert state.value.k_distance == 0.15
    assert state.value.mesh == (17, 17, 9)
    assert state.value.k_index == 25
    assert state.value.k_distance_interval == (0.1476022, 0.15682734)


def test_human_k_index_with_a_shift() -> None:
    state = k_sampling(
        is_metal(_IRON),
        _IRON,
        human=KSamplingHumanInput(k_index=3, shift=(1, 1, 1)),
    )

    assert state.value.shift == (1, 1, 1)


def test_human_k_index_beyond_the_ladder_is_blocked() -> None:
    entries = build_gamma_kmesh_entries(_IRON)

    state = k_sampling(
        is_metal(_IRON),
        _IRON,
        human=KSamplingHumanInput(k_index=len(entries) + 1000),
    )

    assert not state.ok
    assert state.status == "blocked"
    assert "exceeds this structure's own ladder length" in state.root_cause()


def test_human_k_grid_wins_over_k_index_and_k_distance_together() -> None:
    state = k_sampling(
        is_metal(_IRON),
        _IRON,
        human=KSamplingHumanInput(k_grid=(4, 4, 4), k_index=3, k_distance=0.2),
    )

    assert state.value.mesh == (4, 4, 4)
    assert any("k_grid wins" in warning.message for warning in state.value.warnings)


def test_human_k_index_wins_over_k_distance_when_no_grid_is_set() -> None:
    entries = build_gamma_kmesh_entries(_IRON)

    state = k_sampling(
        is_metal(_IRON),
        _IRON,
        human=KSamplingHumanInput(k_index=3, k_distance=0.2),
    )

    assert state.value.mesh == entries[2].mesh
    assert any("k_index wins" in warning.message for warning in state.value.warnings)


@pytest.mark.parametrize(
    ("human", "llm", "source", "k_distance"),
    [
        (KSamplingHumanInput(k_distance=0.2), None, "human", 0.2),
        (None, KSamplingLlmInput(k_distance=0.2), "llm", 0.2),
        (None, None, "heuristic", 0.30),
    ],
    ids=["human", "llm", "heuristic"],
)
def test_a_slab_gets_one_k_point_along_its_vacuum_on_a_ladder_rung(
    human: KSamplingHumanInput | None,
    llm: KSamplingLlmInput | None,
    source: str,
    k_distance: float,
) -> None:
    """#159: every k_distance goes through kmesh, which gives the graphene
    sheet's vacuum axis one division, so the reverse lookup finds the mesh
    on the slab's own ladder, whose rung n is (n, n, 1)."""
    slab = graphene_monolayer(c=15.0)
    n = math.ceil(slab.lattice.reciprocal_lattice.a / k_distance)

    state = k_sampling(_NON_METAL, slab, human=human, llm=llm)

    assert state.source == source
    assert state.value.k_distance == k_distance
    assert state.value.mesh == (n, n, 1)
    assert state.value.k_index == n
    assert (
        state.value.k_distance_interval
        == build_gamma_kmesh_entries(slab)[n - 1].k_distance_interval
    )


def test_a_human_k_grid_on_a_slab_is_kept_verbatim() -> None:
    """An explicit grid wins as given, vacuum axis included. No rung of the
    slab's ladder has two k-points along the vacuum, so k_index stays None."""
    state = k_sampling(
        _NON_METAL,
        graphene_monolayer(c=15.0),
        human=KSamplingHumanInput(k_grid=(15, 15, 2)),
    )

    assert state.value.mesh == (15, 15, 2)
    assert state.value.k_index is None
    assert state.value.k_distance_interval is None


@pytest.mark.parametrize(
    "human",
    [
        KSamplingHumanInput(),
        KSamplingHumanInput(k_distance=0.05),
        KSamplingHumanInput(k_index=1),
    ],
    ids=["heuristic", "k_distance", "k_index"],
)
def test_a_cell_with_vacuum_along_every_axis_is_sampled_at_gamma_only(
    human: KSamplingHumanInput,
) -> None:
    """The isolated C pair of MC3D mc3d-6516 ran on a 3x3x2 mesh (#159). Its
    ladder is the Gamma rung alone, which every k-distance gives, so the
    interval runs from 0 with no upper bound."""
    state = k_sampling(_NON_METAL, carbon_pair_in_a_box(), human=human)

    assert state.value.mesh == (1, 1, 1)
    assert state.value.k_index == 1
    assert state.value.k_distance_interval == (0.0, None)


def test_a_second_rung_on_a_cell_with_vacuum_along_every_axis_is_blocked() -> None:
    state = k_sampling(
        _NON_METAL, carbon_pair_in_a_box(), human=KSamplingHumanInput(k_index=2)
    )

    assert state.status == "blocked"
    assert "exceeds this structure's own ladder length" in state.root_cause()


def _stub_qrf95(monkeypatch: pytest.MonkeyPatch, k_distance: float) -> MlPrediction:
    prediction = MlPrediction(
        value=k_distance,
        provenance=Provenance(
            source="ml",
            model=ModelEvidence(
                model_id="k_points.k_distance.qrf@comp_struct_soap_lattice_metal.v1",
                asset="models/qrf-kpoints@QRF95",
                target_contract="goldilocks.k_distance.mesh_lower_bound.2pi.v1",
                value=k_distance,
                details={"interval": [0.18, 0.45]},
            ),
            citations=("QRF95 citation.",),
        ),
    )
    monkeypatch.setattr(
        predict_module, "predict_k_distance", lambda _structure: prediction
    )
    return prediction


def test_the_heuristic_k_distance_names_is_metal() -> None:
    """#173: the heuristic k_distance follows is_metal (0.15 or 0.30), so the
    record names it and keeps 'heuristic'."""
    state = k_sampling(_NON_METAL, _BCC_IRON)

    assert state.value.k_distance == 0.30
    assert state.source == "heuristic"
    assert state.provenance.field_sources == {
        "k_distance": "heuristic",
        "shift": "heuristic",
    }
    assert state.provenance.derived_from == ("is_metal",)


def test_a_human_shift_on_a_model_k_distance_reads_human_beside_ml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#173: QRF95 decided the distance and the request the shift; the
    record keeps the model's evidence and names neither fact."""
    prediction = _stub_qrf95(monkeypatch, 0.25)

    state = k_sampling(
        _NON_METAL, _BCC_IRON, human=KSamplingHumanInput(shift=(1, 1, 1))
    )

    assert (state.value.k_distance, state.value.shift) == (0.25, (1, 1, 1))
    assert state.source == "human"
    assert state.provenance.field_sources == {"k_distance": "ml", "shift": "human"}
    assert state.provenance.model == prediction.provenance.model
    assert state.provenance.citations == ("QRF95 citation.",)
    assert state.provenance.derived_from == ()


@pytest.mark.parametrize(
    ("human", "llm", "field_sources"),
    [
        (
            KSamplingHumanInput(k_grid=(4, 4, 4), shift=(1, 1, 1)),
            None,
            {"k_grid": "human", "shift": "human"},
        ),
        (
            KSamplingHumanInput(k_index=3),
            None,
            {"k_index": "human", "shift": "heuristic"},
        ),
        (
            KSamplingHumanInput(k_distance=0.2),
            None,
            {"k_distance": "human", "shift": "heuristic"},
        ),
        (
            None,
            KSamplingLlmInput(k_distance=0.2),
            {"k_distance": "llm", "shift": "heuristic"},
        ),
    ],
    ids=["k_grid", "k_index", "k_distance", "llm"],
)
def test_the_setting_the_mesh_came_from_reads_its_tier(
    human: KSamplingHumanInput | None,
    llm: KSamplingLlmInput | None,
    field_sources: dict[str, str],
) -> None:
    state = k_sampling(_NON_METAL, _BCC_IRON, human=human, llm=llm)

    assert state.provenance.field_sources == field_sources
    assert state.source == ("llm" if llm else "human")
    assert state.provenance.derived_from == ()


_PROTOCOL = KSamplingProtocol(k_distance=0.1, note="A task protocol's nscf spacing.")
"""A step's protocol k-point spacing, as the dos task's nscf step gets one."""


def test_a_protocol_k_distance_outranks_qrf95_and_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#174: a step's protocol spacing ranks above QRF95, which is never
    asked (it is trained on scf meshes), and above an llm spacing. The
    record reads 'heuristic' with the protocol as its note, not 'human'."""

    def predict(_structure: Structure) -> MlPrediction:
        raise AssertionError("QRF95 is not asked when the step has a protocol")

    monkeypatch.setattr(predict_module, "predict_k_distance", predict)

    state = k_sampling(
        _NON_METAL,
        _BCC_IRON,
        llm=KSamplingLlmInput(k_distance=0.4),
        protocol=_PROTOCOL,
    )

    assert state.value.k_distance == 0.1
    assert state.value.mesh == k_distance_to_mesh(_BCC_IRON, 0.1)
    assert state.value.shift == (0, 0, 0)
    assert state.provenance == Provenance(
        source="heuristic",
        source_note="A task protocol's nscf spacing.",
        field_sources={"k_distance": "heuristic", "shift": "heuristic"},
    )


def test_without_a_protocol_qrf95_decides_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = _stub_qrf95(monkeypatch, 0.25)

    state = k_sampling(_NON_METAL, _BCC_IRON, protocol=None)

    assert state.value.k_distance == 0.25
    assert state.provenance.model == prediction.provenance.model
    assert state.provenance.source_note is None


@pytest.mark.parametrize(
    ("human", "mesh_from"),
    [
        (KSamplingHumanInput(k_distance=0.2), "k_distance"),
        (KSamplingHumanInput(k_grid=(5, 5, 5)), "k_grid"),
        (KSamplingHumanInput(k_index=2), "k_index"),
    ],
    ids=["k_distance", "k_grid", "k_index"],
)
def test_a_human_mesh_outranks_the_protocol(
    human: KSamplingHumanInput, mesh_from: str
) -> None:
    """#174: the request's own mesh setting wins over the step's protocol
    and reads 'human', without the protocol's note."""
    state = k_sampling(_NON_METAL, _BCC_IRON, human=human, protocol=_PROTOCOL)

    assert state.value == k_sampling(_NON_METAL, _BCC_IRON, human=human).value
    assert state.value.k_distance != 0.1
    assert state.provenance == Provenance(
        source="human",
        field_sources={mesh_from: "human", "shift": "heuristic"},
    )


def test_a_human_shift_applies_on_the_protocol_k_distance() -> None:
    """#174: the request's shift and the protocol's spacing merge field by
    field: a shift alone keeps the protocol mesh."""
    state = k_sampling(
        _NON_METAL,
        _BCC_IRON,
        human=KSamplingHumanInput(shift=(1, 1, 1)),
        protocol=_PROTOCOL,
    )

    assert state.value.k_distance == 0.1
    assert state.value.mesh == k_distance_to_mesh(_BCC_IRON, 0.1)
    assert state.value.shift == (1, 1, 1)
    assert state.provenance == Provenance(
        source="human",
        source_note="A task protocol's nscf spacing.",
        field_sources={"k_distance": "heuristic", "shift": "human"},
    )


_METAL = Resolved("metal", Provenance(source="heuristic"))
_SMEARING = Resolved(
    OccupationsDecision(occupations="smearing", smearing_type="cold", degauss=0.01),
    Provenance(source="heuristic"),
)
_FIXED = Resolved(
    OccupationsDecision(occupations="fixed", smearing_type=None, degauss=None),
    Provenance(source="heuristic"),
)
_TETRAHEDRA = Resolved(
    OccupationsDecision(occupations="tetrahedra_opt", smearing_type=None, degauss=None),
    Provenance(source="heuristic"),
)
_PHONON = PhononKProtocol()
"""The phonon tasks' k rule against the default q-mesh, 0.3 1/A (#215)."""


def _codes(state) -> list[str]:
    return [warning.code for warning in state.value.warnings]


@pytest.mark.parametrize(
    "occupations", [_SMEARING, _TETRAHEDRA], ids=["smearing", "tetrahedra_opt"]
)
def test_a_metal_s_occupations_raise_the_mesh_to_a_multiple_of_the_q_mesh(
    monkeypatch: pytest.MonkeyPatch, occupations: Resolved[OccupationsDecision]
) -> None:
    """#215: QRF95's spacing gives bcc Fe 12x12x12, on which the 11x11x11
    q-points of 0.3 1/A are not differences of k-points; with smearing or
    tetrahedra each axis goes to the next multiple of 11. The record keeps
    QRF95's evidence and says why the mesh is denser; the mesh is rung 22,
    which no single spacing names."""
    prediction = _stub_qrf95(monkeypatch, 0.2747)

    state = k_sampling(_METAL, written_bcc_iron(), occupations, phonon=_PHONON)

    assert state.value.mesh == (22, 22, 22)
    assert state.value.shift == (0, 0, 0)
    assert state.value.k_distance is None
    assert state.value.k_index == 22
    assert state.value.k_distance_interval == (0.14482541, 0.15172186)
    assert state.provenance.field_sources == {"k_distance": "ml", "shift": "heuristic"}
    assert state.provenance.model == prediction.provenance.model
    assert state.provenance.citations == ("QRF95 citation.",)
    assert state.provenance.source_note == (
        "Raised for DFPT from 12x12x12 to 22x22x22: each k-axis to the next "
        "multiple of its q-axis (q-mesh 11x11x11), so that every q-point is a "
        "difference of k-points, without which the phonons of a metal converge "
        "very slowly in k (Quantum ESPRESSO's PHonon user guide, "
        "user_guide.tex:562-565)."
    )
    (notice,) = state.value.warnings
    assert (notice.code, notice.level, notice.category) == (
        "phonon.k_mesh_raised",
        "info",
        "k_sampling",
    )
    assert notice.message == (
        f"with occupations='{occupations.value.occupations}', the k-mesh was "
        "raised from 12x12x12 to 22x22x22, each k-axis to the next multiple of "
        "its q-axis of the 11x11x11 phonon q-mesh, since Quantum ESPRESSO's "
        "PHonon user guide notes that the phonons of a metal converge slowly in k "
        "when q-points are not differences of k-points. This is a convergence "
        "default, not a ph.x requirement: set k_grid, k_index or k_distance to "
        "use your own mesh."
    )


def test_a_request_shift_alone_leaves_the_mesh_to_the_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#215: a shift sets no mesh, so QRF95's 12x12x12 for bcc Fe is still
    raised, and keeps the request's shift."""
    _stub_qrf95(monkeypatch, 0.2747)

    state = k_sampling(
        _METAL,
        written_bcc_iron(),
        _SMEARING,
        KSamplingHumanInput(shift=(1, 1, 1)),
        phonon=_PHONON,
    )

    assert (state.value.mesh, state.value.shift) == ((22, 22, 22), (1, 1, 1))
    assert state.provenance.field_sources == {"k_distance": "ml", "shift": "human"}
    assert _codes(state) == ["phonon.k_mesh_raised"]


@pytest.mark.parametrize(
    ("q", "mesh"),
    [(None, (7, 7, 7)), (QSamplingHumanInput(q_grid=(8, 8, 8)), (8, 8, 8))],
    ids=["default", "q_grid"],
)
def test_fixed_occupations_raise_the_mesh_to_at_least_the_q_mesh(
    monkeypatch: pytest.MonkeyPatch,
    q: QSamplingHumanInput | None,
    mesh: tuple[int, int, int],
) -> None:
    """#215: QRF95 meshes rock-salt NaCl 4x4x4, coarser than its 7x7x7
    q-points at 0.3 1/A, where Petretto et al. found spurious acoustic
    frequencies near Gamma; k goes to the q-mesh, also to a request q_grid
    denser than the default."""
    _stub_qrf95(monkeypatch, 0.4901)

    state = k_sampling(
        _NON_METAL, written_sodium_chloride(), _FIXED, phonon=PhononKProtocol(q)
    )

    assert state.value.mesh == mesh
    assert state.value.k_distance is None
    assert state.provenance.source_note == (
        f"Raised for DFPT from 4x4x4 to {'x'.join(map(str, mesh))}: each k-axis "
        f"to at least its q-axis (q-mesh {'x'.join(map(str, mesh))}), since a "
        "q-mesh denser than the k-mesh can give spurious acoustic frequencies "
        "near Gamma (Petretto et al., Comput. Mater. Sci. 144, 331 (2018))."
    )
    (notice,) = state.value.warnings
    assert notice.code == "phonon.k_mesh_raised"
    assert notice.message.startswith("with occupations='fixed', the k-mesh")
    assert "spurious acoustic frequencies near Gamma" in notice.message
    assert notice.message.endswith(
        "This is a convergence default, not a ph.x requirement: set k_grid, "
        "k_index or k_distance to use your own mesh."
    )


def test_a_mesh_that_already_meets_the_q_mesh_is_left_as_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QRF95's 10x10x10 for diamond Si is denser than its 7x7x7 q-points, so
    fixed occupations keep the decision whole: spacing, rung, no note."""
    _stub_qrf95(monkeypatch, 0.2174)

    state = k_sampling(_NON_METAL, written_silicon(), _FIXED, phonon=_PHONON)

    assert state.value.mesh == (10, 10, 10)
    assert state == k_sampling(_NON_METAL, written_silicon(), _FIXED)


@pytest.mark.parametrize(
    ("structure", "occupations", "human", "codes"),
    [
        (
            written_bcc_iron(),
            _SMEARING,
            KSamplingHumanInput(k_grid=(4, 4, 4)),
            ["phonon.k_grid_coarser_than_q", "phonon.k_grid_not_commensurate"],
        ),
        (
            written_bcc_iron(),
            _SMEARING,
            KSamplingHumanInput(k_grid=(12, 12, 12)),
            ["phonon.k_grid_not_commensurate"],
        ),
        (
            written_bcc_iron(),
            _TETRAHEDRA,
            KSamplingHumanInput(k_grid=(12, 12, 12)),
            ["phonon.k_grid_not_commensurate"],
        ),
        (
            written_sodium_chloride(),
            _FIXED,
            KSamplingHumanInput(k_distance=0.49),
            ["phonon.k_grid_coarser_than_q"],
        ),
        (
            written_bcc_iron(),
            _SMEARING,
            KSamplingHumanInput(k_index=22),
            [],
        ),
    ],
    ids=[
        "k_grid-coarse",
        "k_grid-off-multiple",
        "k_grid-off-multiple-tetrahedra",
        "k_distance-fixed",
        "k_index",
    ],
)
def test_a_request_mesh_is_used_as_given_with_what_it_misses(
    structure: Structure,
    occupations: Resolved[OccupationsDecision],
    human: KSamplingHumanInput,
    codes: list[str],
) -> None:
    """#215: the request's own k_grid, k_index or k_distance is not raised. It
    is warned about where it is coarser than the q-mesh (Fe's 11x11x11,
    NaCl's 7x7x7) and, with smearing or tetrahedra, where it is not a
    multiple of it; fixed occupations need no multiple."""
    state = k_sampling(_METAL, structure, occupations, human, phonon=_PHONON)

    plain = k_sampling(_METAL, structure, occupations, human)
    assert state.value.mesh == plain.value.mesh
    assert state.provenance == plain.provenance
    assert _codes(state) == codes
    assert all(warning.level == "warning" for warning in state.value.warnings)


def _fcc_cerium() -> Structure:
    """fcc Ce (Fm-3m), Materials Project mp-28, in its 4-atom conventional
    cell (a = 4.672 A)."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.6724), ["Ce"], [[0.0, 0.0, 0.0]]
    )


def test_a_smearing_run_with_a_lanthanide_is_told_of_the_denser_metal_mesh() -> None:
    """#215: a smearing run holding a lanthanide or an actinide hears that
    Nascimento et al. advise k_distance 0.10 1/A for metals of that kind; its
    heuristic 9x9x9 is raised to 10x10x10 against the 5x5x5 q-mesh, and a
    request 8x8x8 is kept, with the warning that it is not a multiple of the
    q-mesh. A run on fixed occupations keeps 9x9x9 and hears nothing."""
    structure = _fcc_cerium()

    smearing = k_sampling(_METAL, structure, _SMEARING, phonon=_PHONON)
    requested = k_sampling(
        _METAL,
        structure,
        _SMEARING,
        KSamplingHumanInput(k_grid=(8, 8, 8)),
        phonon=_PHONON,
    )
    fixed = k_sampling(_METAL, structure, _FIXED, phonon=_PHONON)

    assert smearing.value.mesh == (10, 10, 10)
    assert _codes(smearing) == ["phonon.k_mesh_raised", "phonon.lanthanide_actinide_k"]
    notice = smearing.value.warnings[-1]
    assert (notice.level, notice.category) == ("info", "k_sampling")
    assert notice.message.startswith(
        "the structure holds Ce and the run uses occupations='smearing': if it "
        "is a metal, Nascimento et al. advise k_distance 0.10 1/Angstrom"
    )
    assert requested.value.mesh == (8, 8, 8)
    assert _codes(requested) == [
        "phonon.k_grid_not_commensurate",
        "phonon.lanthanide_actinide_k",
    ]
    assert requested.value.warnings[-1] == notice
    assert (fixed.value.mesh, fixed.value.warnings) == ((9, 9, 9), ())


def test_a_q_mesh_too_large_for_q2r_x_leaves_the_mesh_alone() -> None:
    """q_distance 0.02 gives Si 101x101x101 q-points, which the q record
    refuses without counting them; the k-mesh is not raised against it."""
    q = PhononKProtocol(QSamplingHumanInput(q_distance=0.02))

    state = k_sampling(_NON_METAL, written_silicon(), _FIXED, phonon=q)

    assert state == k_sampling(_NON_METAL, written_silicon(), _FIXED)


def test_blocked_occupations_block_the_phonon_mesh() -> None:
    state = k_sampling(
        _METAL, written_bcc_iron(), Blocked(by="synthetic failure"), phonon=_PHONON
    )

    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"
