from __future__ import annotations

from goldilocks_core.advisors.cutoffs import CutoffsHumanInput, cutoffs
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Unavailable


def _metadata(
    element: str, *, ecutwfc_ry: float | None, ecutrho_ry: float | None = None
) -> PseudoMetadata:
    return PseudoMetadata(
        filepath=f"{element}.upf",
        filename=f"{element}.upf",
        header_format="UPF v2",
        element=element,
        cutoffs={"ecutwfc_ry": ecutwfc_ry, "ecutrho_ry": ecutrho_ry},
    )


def _table(*, charge_density_dual: float | None) -> Resolved[PseudoTable]:
    table = PseudoTable(
        id="pseudodojo-pbe-efficiency-sr",
        provider="pseudodojo",
        upstream_table="pseudodojo",
        version="0.4",
        functional="pbe",
        relativistic="scalar",
        accuracy="efficiency",
        licence="CC-BY-4.0",
        citation="van Setten et al.",
        elements=("Fe", "O"),
        asset=AssetSpec(
            id="pseudopotentials/pseudodojo-pbe-efficiency-sr",
            version="0.4",
            files=(
                AssetFile(role="pseudopotential", path="Fe.upf", url="file://Fe.upf"),
            ),
        ),
        charge_density_dual=charge_density_dual,
    )
    return Resolved(table, Provenance(source="heuristic"))


def test_sssp_style_pseudopotentials_give_explicit_cutoffs_directly() -> None:
    pseudos = Resolved(
        (
            _metadata("Fe", ecutwfc_ry=90.0, ecutrho_ry=720.0),
            _metadata("O", ecutwfc_ry=50.0, ecutrho_ry=400.0),
        ),
        Provenance(source="heuristic"),
    )

    state = cutoffs(pseudos)

    assert state.ok
    assert state.value.ecutwfc_ry == 90.0
    assert state.value.ecutrho_ry == 720.0
    assert state.value.warnings == ()


def test_pseudodojo_style_pseudopotentials_derive_ecutrho_via_table_dual() -> None:
    """PseudoDojo (this codebase's default provider) only publishes ecutwfc;
    ecutrho is derived from the table's own charge_density_dual, and one
    notice per decision says so, naming the elements and the table (#180)."""
    pseudos = Resolved(
        (_metadata("Fe", ecutwfc_ry=40.0), _metadata("O", ecutwfc_ry=45.0)),
        Provenance(source="heuristic"),
    )

    state = cutoffs(pseudos, table=_table(charge_density_dual=4.0))

    assert state.ok
    assert state.source == "heuristic"
    assert state.value.ecutwfc_ry == 45.0
    assert state.value.ecutrho_ry == 180.0  # 4 x max(40, 45)
    (warning,) = state.value.warnings
    assert warning.code == "cutoffs.ecutrho_derived_from_dual"
    assert warning.level == "info"
    assert warning.message == (
        "ecutrho derived as charge_density_dual x ecutwfc = 4 x 45 = 180 Ry: "
        "table pseudodojo-pbe-efficiency-sr publishes no density cutoff for Fe, O"
    )


def test_a_human_ecutwfc_scales_a_derived_ecutrho() -> None:
    """#180: ecutrho is charge_density_dual x the resolved ecutwfc, so a
    human ecutwfc_ry of 150 Ry on a dual-4 table gives 600 Ry (QE's own
    norm-conserving default), not 4 x the published 45 Ry."""
    pseudos = Resolved(
        (_metadata("Fe", ecutwfc_ry=40.0), _metadata("O", ecutwfc_ry=45.0)),
        Provenance(source="heuristic"),
    )

    state = cutoffs(
        pseudos,
        table=_table(charge_density_dual=4.0),
        human=CutoffsHumanInput(ecutwfc_ry=150.0),
    )

    assert (state.value.ecutwfc_ry, state.value.ecutrho_ry) == (150.0, 600.0)
    assert state.source == "human"
    (warning,) = state.value.warnings
    assert "= 4 x 150 = 600 Ry" in warning.message


def test_a_human_ecutrho_is_not_reported_as_derived() -> None:
    pseudos = Resolved(
        (_metadata("Fe", ecutwfc_ry=40.0), _metadata("O", ecutwfc_ry=45.0)),
        Provenance(source="heuristic"),
    )

    state = cutoffs(
        pseudos,
        table=_table(charge_density_dual=4.0),
        human=CutoffsHumanInput(ecutrho_ry=500.0),
    )

    assert (state.value.ecutwfc_ry, state.value.ecutrho_ry) == (45.0, 500.0)
    assert state.value.warnings == ()


def test_missing_ecutrho_and_no_dual_blocks() -> None:
    pseudos = Resolved(
        (_metadata("Fe", ecutwfc_ry=40.0),), Provenance(source="heuristic")
    )

    state = cutoffs(pseudos, table=_table(charge_density_dual=None))

    assert not state.ok
    assert state.status == "blocked"
    assert "Fe" in state.root_cause()


def test_missing_ecutwfc_blocks_even_with_a_dual_available() -> None:
    pseudos = Resolved(
        (_metadata("Fe", ecutwfc_ry=None),), Provenance(source="heuristic")
    )

    state = cutoffs(pseudos, table=_table(charge_density_dual=4.0))

    assert not state.ok
    assert "Fe" in state.root_cause()


def test_blocked_pseudos_propagates_as_blocked() -> None:
    state = cutoffs(Blocked(by="pseudopotential selection failed"))

    assert not state.ok
    assert state.root_cause() == "pseudopotential selection failed"


def test_unavailable_pseudos_is_treated_as_blocked_not_a_default() -> None:
    state = cutoffs(Unavailable(reason="synthetic failure"))

    assert not state.ok
    assert state.status == "blocked"
    assert state.root_cause() == "synthetic failure"


def test_human_can_override_both_cutoffs_without_needing_pseudos() -> None:
    state = cutoffs(
        Blocked(by="irrelevant"),
        human=CutoffsHumanInput(ecutwfc_ry=80.0, ecutrho_ry=320.0),
    )

    assert state.ok
    assert state.value.ecutwfc_ry == 80.0
    assert state.value.ecutrho_ry == 320.0
    assert state.source == "human"


def test_human_can_override_a_single_field_the_other_stays_heuristic() -> None:
    pseudos = Resolved(
        (_metadata("Fe", ecutwfc_ry=90.0, ecutrho_ry=720.0),),
        Provenance(source="heuristic"),
    )

    state = cutoffs(pseudos, human=CutoffsHumanInput(ecutwfc_ry=100.0))

    assert state.value.ecutwfc_ry == 100.0
    assert state.value.ecutrho_ry == 720.0
    assert state.source == "human"
