from __future__ import annotations

import pytest

from goldilocks_core.advisors.pseudo_selection import (
    PseudoRequirements,
    is_table_eligible,
    pseudo_requirements,
    requires_sssp,
    select_metadata_for_elements,
    select_pseudopotential_table,
)
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable, load_tables
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.resolution import Provenance


def _table(
    table_id: str,
    *,
    provider: str = "pseudodojo",
    functional: str = "PBEsol",
    accuracy: str = "efficiency",
    relativistic: str = "scalar",
    elements: tuple[str, ...] = ("Si",),
    citation: str = "fixture citation",
) -> PseudoTable:
    return PseudoTable(
        id=table_id,
        provider=provider,
        upstream_table="fixture",
        version="1",
        functional=functional,
        relativistic=relativistic,
        accuracy=accuracy,
        licence="fixture licence",
        citation=citation,
        elements=elements,
        asset=AssetSpec(
            f"pseudopotentials/{table_id}",
            "1",
            (AssetFile("pseudopotentials", "source/upf.tgz", "file:///fixture.tgz"),),
        ),
        charge_density_dual=4.0 if provider == "pseudodojo" else None,
    )


def _requirements(**overrides: object) -> PseudoRequirements:
    defaults = {
        "functional": "PBEsol",
        "accuracy": "efficiency",
        "relativistic": "scalar",
    }
    defaults.update(overrides)
    return PseudoRequirements(**defaults)


def test_requires_sssp_is_true_for_lanthanides_and_actinides() -> None:
    assert requires_sssp({"La"}) is True
    assert requires_sssp({"U"}) is True
    assert requires_sssp({"Si", "O"}) is False


def test_pseudo_requirements_relativistic_follows_spin_orbit_enabled() -> None:
    on = pseudo_requirements("PBEsol", spin_orbit_enabled=True)
    off = pseudo_requirements("PBEsol", spin_orbit_enabled=False)

    assert on.relativistic == "full"
    assert off.relativistic == "scalar"


def test_explicit_table_id_resolves_when_compatible() -> None:
    tables = {"fixture": _table("fixture")}

    state = select_pseudopotential_table(
        tables, table_id="fixture", elements={"Si"}, requirements=_requirements()
    )

    assert state.ok
    assert state.value.id == "fixture"


@pytest.mark.parametrize("table_id", [None, "sssp"], ids=["automatic", "pinned"])
def test_the_selected_table_record_cites_that_table(table_id: str | None) -> None:
    """#156: the bundle cites what its records cite, so the pseudo_table
    record carries the selected table's citation, however it was chosen."""
    tables = {
        "dojo": _table("dojo", elements=("Si",), citation="van Setten et al."),
        "sssp": _table(
            "sssp", provider="sssp", elements=("La", "Si"), citation="Prandini et al."
        ),
    }

    state = select_pseudopotential_table(
        tables, table_id=table_id, elements={"La"}, requirements=_requirements()
    )

    assert state.value.id == "sssp"
    assert state.provenance.citations == ("Prandini et al.",)


def test_a_pinned_table_reads_human() -> None:
    """#173: pseudo_table_id=sssp-pbesol-efficiency-sr on bcc Fe read
    'heuristic'. A pinned table is the request's choice."""
    tables = {"dojo": _table("dojo"), "sssp": _table("sssp", provider="sssp")}

    state = select_pseudopotential_table(
        tables, table_id="sssp", elements={"Si"}, requirements=_requirements()
    )

    assert state.value.id == "sssp"
    assert state.provenance == Provenance(
        source="human",
        field_sources={"pseudo_table_id": "human"},
        citations=("fixture citation",),
    )


def test_an_automatic_table_names_the_records_its_requirements_come_from() -> None:
    """#173: automatic selection follows the functional and the magnetic
    decision's spin-orbit switch, so it stays 'heuristic' and names both."""
    tables = {"dojo": _table("dojo"), "sssp": _table("sssp", provider="sssp")}

    state = select_pseudopotential_table(
        tables, table_id=None, elements={"Si"}, requirements=_requirements()
    )

    assert state.value.id == "dojo"
    assert state.provenance.derived_from == ("functional", "magnetic")
    assert state.provenance == Provenance(
        source="heuristic",
        derived_from=("functional", "magnetic"),
        citations=("fixture citation",),
    )


def test_explicit_unknown_table_id_is_unavailable_not_a_raise() -> None:
    """v2 epic 5 (#5) bug fix: v1 raised PseudoTableMismatch here."""
    state = select_pseudopotential_table(
        {"fixture": _table("fixture")},
        table_id="not-a-table",
        elements={"Si"},
        requirements=_requirements(),
    )

    assert not state.ok
    assert state.status == "unavailable"
    assert "unknown pseudopotential table" in state.reason


def test_explicit_table_id_mismatched_functional_is_unavailable_with_alternatives() -> (
    None
):
    tables = {
        "wrong": _table("wrong", functional="LDA"),
        "right": _table("right", functional="PBEsol"),
    }

    state = select_pseudopotential_table(
        tables, table_id="wrong", elements={"Si"}, requirements=_requirements()
    )

    assert not state.ok
    assert "functional is LDA, requested PBEsol" in state.reason
    assert "right" in state.reason


def test_automatic_selection_picks_the_only_compatible_table() -> None:
    tables = {"fixture": _table("fixture")}

    state = select_pseudopotential_table(
        tables, table_id=None, elements={"Si"}, requirements=_requirements()
    )

    assert state.ok
    assert state.value.id == "fixture"


@pytest.mark.parametrize(
    ("element", "provider"), [("La", "sssp"), ("Si", "pseudodojo")]
)
def test_automatic_selection_picks_sssp_for_lanthanides_and_pseudodojo_otherwise(
    element: str, provider: str
) -> None:
    """The provider rule, not table-id order, picks PseudoDojo for Si: an
    operator registry may name its tables freely, and here the SSSP table
    sorts first."""
    tables = {
        "a-sssp": _table("a-sssp", provider="sssp", elements=("La", "Si")),
        "dojo": _table("dojo", provider="pseudodojo", elements=("La", "Si")),
    }

    state = select_pseudopotential_table(
        tables, table_id=None, elements={element}, requirements=_requirements()
    )

    assert state.value.provider == provider


def test_automatic_selection_excludes_dojo_tables_missing_lanthanide_coverage() -> None:
    """is_table_eligible's rule, exercised through select_pseudopotential_table:
    a PseudoDojo table is never eligible for lanthanide/actinide elements
    even if it happens to list them, because requires_sssp forces sssp."""
    sssp_table = _table("sssp", provider="sssp", elements=("La",))

    assert is_table_eligible(_table("dojo", elements=("La",)), {"La"}) is False
    assert is_table_eligible(sssp_table, {"La"}) is True


def test_automatic_selection_with_no_match_is_unavailable_not_a_raise() -> None:
    tables = {"fixture": _table("fixture", elements=("Si",))}

    state = select_pseudopotential_table(
        tables, table_id=None, elements={"Fe"}, requirements=_requirements()
    )

    assert not state.ok
    assert state.reason == (
        "no pseudopotential table satisfies PBEsol efficiency scalar for Fe: "
        "fixture: missing elements Fe"
    )


class TestAutomaticRefusalAgainstTheRegistry:
    """#182: the automatic refusal names, for every registered table that
    matches the functional and accuracy, the constraints that rejected it,
    so a routing rule reads differently from a coverage gap."""

    def test_lanthanide_soc_names_the_sssp_rule_and_the_scalar_tables(self) -> None:
        state = select_pseudopotential_table(
            load_tables(),
            table_id=None,
            elements={"La", "O"},
            requirements=_requirements(relativistic="full"),
        )

        assert state.status == "unavailable"
        assert state.reason == (
            "no pseudopotential table satisfies PBEsol efficiency full for La, O: "
            "pseudodojo-pbesol-efficiency-fr: lanthanide and actinide elements "
            "require an SSSP table; "
            "pseudodojo-pbesol-efficiency-sr: relativistic treatment is scalar, "
            "requested full and lanthanide and actinide elements require an SSSP "
            "table; "
            "sssp-pbesol-efficiency-sr: relativistic treatment is scalar, "
            "requested full"
        )

    def test_uncovered_lanthanide_also_names_the_missing_element(self) -> None:
        state = select_pseudopotential_table(
            load_tables(),
            table_id=None,
            elements={"Ce", "Te"},
            requirements=_requirements(relativistic="full"),
        )

        assert state.reason.startswith(
            "no pseudopotential table satisfies PBEsol efficiency full for Ce, Te: "
            "pseudodojo-pbesol-efficiency-fr: lanthanide and actinide elements "
            "require an SSSP table and missing elements Ce; "
        )
        assert state.reason.endswith(
            "; sssp-pbesol-efficiency-sr: relativistic treatment is scalar, "
            "requested full"
        )

    def test_heavy_element_under_lda_soc_names_the_only_lda_table(self) -> None:
        state = select_pseudopotential_table(
            load_tables(),
            table_id=None,
            elements={"Pb"},
            requirements=_requirements(functional="LDA", relativistic="full"),
        )

        assert state.reason == (
            "no pseudopotential table satisfies LDA efficiency full for Pb: "
            "pseudodojo-lda-efficiency-sr: relativistic treatment is scalar, "
            "requested full"
        )

    def test_functional_without_a_table_says_none_is_registered(self) -> None:
        state = select_pseudopotential_table(
            load_tables(),
            table_id=None,
            elements={"Si"},
            requirements=_requirements(functional="SCAN"),
        )

        assert state.reason == (
            "no pseudopotential table satisfies SCAN efficiency scalar for Si: "
            "no registered table has functional SCAN and accuracy efficiency"
        )


class TestExplicitRefusalAgainstTheRegistry:
    """The pinned-table refusal keeps its format: the pinned table's own
    problems, then every table that would satisfy the request."""

    def test_pinned_fr_table_for_a_lanthanide_names_the_sssp_rule(self) -> None:
        state = select_pseudopotential_table(
            load_tables(),
            table_id="pseudodojo-pbesol-efficiency-fr",
            elements={"La", "O"},
            requirements=_requirements(relativistic="full"),
        )

        assert state.reason == (
            "pseudopotential table 'pseudodojo-pbesol-efficiency-fr' does not "
            "satisfy the request: lanthanide and actinide elements require an "
            "SSSP table; matching tables: none"
        )

    def test_pinned_table_with_two_problems_lists_both_and_the_matches(self) -> None:
        state = select_pseudopotential_table(
            load_tables(),
            table_id="pseudodojo-pbe-efficiency-fr",
            elements={"Pb"},
            requirements=_requirements(),
        )

        assert state.reason == (
            "pseudopotential table 'pseudodojo-pbe-efficiency-fr' does not satisfy "
            "the request: functional is PBE, requested PBEsol; relativistic "
            "treatment is full, requested scalar; matching tables: "
            "pseudodojo-pbesol-efficiency-sr, sssp-pbesol-efficiency-sr"
        )


class TestSelectMetadataForElements:
    def test_selects_exactly_the_requested_elements(self) -> None:
        metadata = (
            PseudoMetadata(
                filepath="/store/Si.upf",
                filename="Si.upf",
                header_format="attr",
                element="Si",
            ),
            PseudoMetadata(
                filepath="/store/O.upf",
                filename="O.upf",
                header_format="attr",
                element="O",
            ),
            PseudoMetadata(
                filepath="/store/Fe.upf",
                filename="Fe.upf",
                header_format="attr",
                element="Fe",
            ),
        )

        state = select_metadata_for_elements(metadata, {"Si", "O"})

        assert state.ok
        assert {item.element for item in state.value} == {"Si", "O"}
        assert state.provenance.derived_from == ("pseudo_table",)
        assert state.provenance == Provenance(
            source="heuristic", derived_from=("pseudo_table",)
        )

    def test_missing_element_is_unavailable_not_a_raise(self) -> None:
        metadata = (
            PseudoMetadata(
                filepath="/store/Si.upf",
                filename="Si.upf",
                header_format="attr",
                element="Si",
            ),
        )

        state = select_metadata_for_elements(metadata, {"Si", "O"})

        assert not state.ok
        assert state.status == "unavailable"
        assert "O" in state.reason

    def test_duplicate_element_entries_are_unavailable_not_silently_first_picked(
        self,
    ) -> None:
        metadata = (
            PseudoMetadata(
                filepath="/store/Si-a.upf",
                filename="Si-a.upf",
                header_format="attr",
                element="Si",
            ),
            PseudoMetadata(
                filepath="/store/Si-b.upf",
                filename="Si-b.upf",
                header_format="attr",
                element="Si",
            ),
        )

        state = select_metadata_for_elements(metadata, {"Si"})

        assert not state.ok
        assert state.status == "unavailable"
        assert "Si" in state.reason

    def test_result_is_deterministically_ordered_by_element(self) -> None:
        metadata = (
            PseudoMetadata(
                filepath="/store/O.upf",
                filename="O.upf",
                header_format="attr",
                element="O",
            ),
            PseudoMetadata(
                filepath="/store/Fe.upf",
                filename="Fe.upf",
                header_format="attr",
                element="Fe",
            ),
        )

        state = select_metadata_for_elements(metadata, {"O", "Fe"})

        assert state.ok
        assert [item.element for item in state.value] == ["Fe", "O"]
