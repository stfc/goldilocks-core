from typing import Any

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.selection import select_pseudopotentials
from goldilocks_core.serialization import to_portable


def make_structure(*species: str) -> Structure:
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=list(species or ("Si",)),
        coords=[
            [index / max(len(species), 1), 0.0, 0.0]
            for index in range(len(species) or 1)
        ],
    )


def make_requirements(
    *,
    functional: str = "PBEsol",
    accuracy: str = "efficiency",
    pseudo_type: str | None = "NC",
    relativistic: str = "scalar",
) -> dict[str, Any]:
    return {
        "functional": functional,
        "accuracy": accuracy,
        "pseudo_type": pseudo_type,
        "relativistic": relativistic,
        "provenance": Provenance(source="default", reason="test requirements"),
    }


def make_metadata(
    *,
    element: str = "Si",
    filename: str = "Si.UPF",
    provider: str | None = "sssp",
    accuracy: str | None = "efficiency",
    functional: str = "PBEsol",
    pseudo_type: str | None = "NC",
    relativistic: str | None = "scalar",
    ecutwfc_ry: float | None = 30.0,
    ecutrho_ry: float | None = 120.0,
    frozen_4f_core: bool = False,
) -> PseudoMetadata:
    cutoffs = (
        None
        if ecutwfc_ry is None and ecutrho_ry is None
        else {"ecutwfc_ry": ecutwfc_ry, "ecutrho_ry": ecutrho_ry}
    )
    return PseudoMetadata(
        filepath=f"/pseudo/{filename}",
        filename=filename,
        header_format="attr",
        provider=provider,
        accuracy=accuracy,
        element=element,
        pseudo_type=pseudo_type,
        functional=functional,
        relativistic=relativistic,
        cutoffs=cutoffs,
        source_identifier=f"source/{filename}",
        frozen_4f_core=frozen_4f_core,
    )


@pytest.mark.parametrize(
    "source_identifier",
    (
        "/srv/provider/Si.UPF",
        r"C:\provider\Si.UPF",
        r"\\server\share\Si.UPF",
        "~/provider/Si.UPF",
        r"~\provider\Si.UPF",
        "~willow/provider/Si.UPF",
    ),
)
def test_pseudo_source_identity_rejects_host_path_forms(
    source_identifier: str,
) -> None:
    with pytest.raises(ValueError, match="portable source identity"):
        PseudoMetadata(
            filepath="operator/Si.UPF",
            filename="Si.UPF",
            header_format="attr",
            source_identifier=source_identifier,
        )


@pytest.mark.parametrize(
    "source_identifier",
    ("provider/table/Si.UPF", "https://provider.example/table/Si.UPF"),
)
def test_pseudo_source_identity_retains_portable_provider_identifiers(
    source_identifier: str,
) -> None:
    metadata = PseudoMetadata(
        filepath="operator/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        source_identifier=source_identifier,
    )

    assert metadata.source_identifier == source_identifier
    assert to_portable(metadata)["source_identifier"] == source_identifier


def test_selects_complete_candidate_matching_every_requirement() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(),
        [make_metadata()],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["element"] == "Si"
    assert pseudo["filename"] == "Si.UPF"
    assert pseudo["filepath"] == "/pseudo/Si.UPF"
    assert pseudo["functional"] == "PBEsol"
    assert pseudo["relativistic"] == "scalar"
    assert pseudo["ecutwfc_ry"] == 30.0
    assert pseudo["ecutrho_ry"] == 120.0
    assert pseudo["provenance"].source == "lookup"
    assert pseudo["provenance"].data_source == "sssp"
    assert pseudo["warnings"] == []
    assert selection["warnings"] == []


def test_selects_by_registered_accuracy_not_filename() -> None:
    efficiency = make_metadata(
        filename="looks-like-precision.UPF",
        accuracy="efficiency",
        ecutwfc_ry=30,
        ecutrho_ry=120,
    )
    precision = make_metadata(
        filename="looks-like-efficiency.UPF",
        accuracy="precision",
        ecutwfc_ry=60,
        ecutrho_ry=240,
    )

    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(accuracy="precision"),
        [efficiency, precision],
    )

    assert selection["pseudopotentials"][0]["filename"] == "looks-like-efficiency.UPF"
    assert selection["pseudopotentials"][0]["ecutwfc_ry"] == 60.0


def test_unknown_custom_accuracy_is_eligible_with_warning() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(accuracy="precision"),
        [make_metadata(provider=None, accuracy=None)],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] == "Si.UPF"
    assert pseudo["warnings"] == [
        "Selected custom pseudopotential for Si has no registered accuracy tier; "
        "requested precision.",
    ]
    assert selection["warnings"] == pseudo["warnings"]


def test_known_wrong_accuracy_is_not_used_as_fallback() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(accuracy="precision"),
        [make_metadata(accuracy="efficiency")],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] is None
    assert pseudo["provenance"].source == "fallback"
    assert "registered accuracy precision" in pseudo["warnings"][0]


def test_prefers_complete_cutoffs_within_matching_candidates() -> None:
    incomplete = make_metadata(
        filename="A-incomplete.UPF",
        ecutwfc_ry=30,
        ecutrho_ry=None,
    )
    complete = make_metadata(
        filename="Z-complete.UPF",
        ecutwfc_ry=35,
        ecutrho_ry=140,
    )

    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(),
        [incomplete, complete],
    )

    assert selection["pseudopotentials"][0]["filename"] == "Z-complete.UPF"
    assert selection["warnings"] == []


def test_reports_missing_cutoff_fields_without_sanitizing_values() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(),
        [make_metadata(ecutwfc_ry=30, ecutrho_ry=None)],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["ecutwfc_ry"] == 30.0
    assert pseudo["ecutrho_ry"] is None
    assert pseudo["warnings"] == [
        "Selected pseudopotential for Si is missing cutoff metadata for "
        "ecutrho_ry; provide finite positive values before generation.",
    ]


def test_normalized_functional_aliases_match() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(functional="PBEsol"),
        [make_metadata(functional="PBESOL")],
    )

    assert selection["pseudopotentials"][0]["filename"] == "Si.UPF"


def test_functional_disagreement_returns_actionable_warning() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(functional="PBEsol"),
        [make_metadata(functional="PBE")],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] is None
    assert pseudo["warnings"] == [
        "Available pseudopotentials for Si do not match functional PBEsol; "
        "available: PBE.",
    ]


def test_pseudo_type_and_relativistic_treatment_are_required() -> None:
    wrong_type = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(pseudo_type="NC"),
        [make_metadata(pseudo_type="PAW")],
    )
    wrong_relativistic = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(relativistic="scalar"),
        [make_metadata(relativistic="full")],
    )

    assert wrong_type["pseudopotentials"][0]["filename"] is None
    assert "matches type NC" in wrong_type["warnings"][0]
    assert wrong_relativistic["pseudopotentials"][0]["filename"] is None
    assert "scalar PBEsol" in wrong_relativistic["warnings"][0]


def test_sssp_scalar_table_preserves_nonrelativistic_file_treatment() -> None:
    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(relativistic="scalar"),
        [make_metadata(provider="sssp", relativistic="non-relativistic")],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] == "Si.UPF"
    assert pseudo["relativistic"] == "non-relativistic"
    assert pseudo["warnings"] == [
        "Selected SSSP pseudopotential for Si declares non-relativistic "
        "treatment within a scalar table; verify this compatibility.",
    ]


def test_frozen_4f_core_warning_survives_selection() -> None:
    selection = select_pseudopotentials(
        make_structure("Ce"),
        make_requirements(),
        [
            make_metadata(
                element="Ce",
                filename="Ce.upf",
                frozen_4f_core=True,
            )
        ],
    )

    assert "freezes 4f electrons" in selection["warnings"][0]
    assert "Ce, Eu, or Yb" in selection["warnings"][0]


def test_lanthanide_routes_to_sssp_when_both_providers_available() -> None:
    """Never select a PseudoDojo pseudo for a lanthanide when SSSP exists."""
    dojo = make_metadata(
        element="Ce",
        filename="Ce-pdojo.UPF",
        provider="pseudodojo",
        frozen_4f_core=True,
    )
    sssp = make_metadata(element="Ce", filename="Ce-sssp.UPF", provider="sssp")

    selection = select_pseudopotentials(
        make_structure("Ce"),
        make_requirements(),
        [dojo, sssp],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] == "Ce-sssp.UPF"
    assert pseudo["provenance"].data_source == "sssp"
    assert pseudo["warnings"] == []


def test_lanthanide_without_sssp_returns_actionable_fallback() -> None:
    """Refuse PseudoDojo lanthanide pseudos and say how to fix it."""
    selection = select_pseudopotentials(
        make_structure("Ce"),
        make_requirements(),
        [
            make_metadata(
                element="Ce",
                provider="pseudodojo",
                frozen_4f_core=True,
            )
        ],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] is None
    assert pseudo["provenance"].source == "fallback"
    assert "only SSSP pseudopotentials" in pseudo["warnings"][0]
    assert (
        "goldilocks assets install sssp-pbesol-efficiency-sr" in pseudo["warnings"][0]
    )
    assert "--pseudo-table sssp-pbesol-efficiency-sr" in pseudo["warnings"][0]


def test_actinide_without_sssp_returns_actionable_fallback() -> None:
    """No PseudoDojo table covers actinides; require SSSP."""
    selection = select_pseudopotentials(
        make_structure("U"),
        make_requirements(),
        [make_metadata(element="U", provider="pseudodojo")],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] is None
    assert "no PseudoDojo table covers actinides" in pseudo["warnings"][0]


def test_lanthanide_full_relativistic_request_notes_no_soc() -> None:
    """SSSP has no fully-relativistic table; say so for Ln/An with SOC."""
    selection = select_pseudopotentials(
        make_structure("Ce"),
        make_requirements(relativistic="full"),
        [make_metadata(element="Ce", relativistic="scalar")],
    )

    pseudo = selection["pseudopotentials"][0]
    assert pseudo["filename"] is None
    assert "no spin-orbit coupling" in pseudo["warnings"][0]


def test_sssp_preferred_over_pseudodojo_in_ranking() -> None:
    """Rank SSSP ahead of PseudoDojo for equal complete candidates."""
    dojo = make_metadata(filename="A-dojo.UPF", provider="pseudodojo")
    sssp = make_metadata(filename="Z-sssp.UPF", provider="sssp")

    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(),
        [dojo, sssp],
    )

    assert selection["pseudopotentials"][0]["filename"] == "Z-sssp.UPF"


def test_complete_cutoffs_outrank_sssp_preference() -> None:
    """Cutoff completeness still beats provider preference in ranking."""
    incomplete_sssp = make_metadata(
        filename="A-sssp.UPF",
        provider="sssp",
        ecutwfc_ry=30,
        ecutrho_ry=None,
    )
    complete_dojo = make_metadata(
        filename="Z-dojo.UPF",
        provider="pseudodojo",
        ecutwfc_ry=35,
        ecutrho_ry=140,
    )

    selection = select_pseudopotentials(
        make_structure("Si"),
        make_requirements(),
        [incomplete_sssp, complete_dojo],
    )

    assert selection["pseudopotentials"][0]["filename"] == "Z-dojo.UPF"


def test_selection_is_complete_and_deterministic_for_multiple_elements() -> None:
    selection = select_pseudopotentials(
        make_structure("Na", "Cl"),
        make_requirements(),
        [
            make_metadata(element="Na", filename="Na.upf"),
            make_metadata(element="Cl", filename="Cl.upf"),
        ],
    )

    assert [pseudo["element"] for pseudo in selection["pseudopotentials"]] == [
        "Cl",
        "Na",
    ]
