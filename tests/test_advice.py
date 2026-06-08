import pytest

from goldilocks_core.advice import advise_parameters
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    StructureAnalysisRecord,
)


def make_analysis(
    *,
    magnetic_elements: tuple[str, ...] = (),
    heavy_elements: tuple[str, ...] = (),
) -> StructureAnalysisRecord:
    """Build an analysis record for advice tests."""
    return StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=bool(magnetic_elements),
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=bool(heavy_elements),
        magnetic_elements=magnetic_elements,
        heavy_elements=heavy_elements,
    )


def test_advise_parameters_records_user_hint_provenance() -> None:
    """Let hints override Core defaults with user-hint provenance."""
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(
            k_grid=(2, 2, 1),
            spin_polarized=True,
            spin_orbit_coupling=True,
            pseudo_mode="precision",
            smearing_type="cold",
            smearing_width_ry=0.01,
        ),
    )

    assert advice.k_points.explicit_grid == (2, 2, 1)
    assert advice.k_points.provenance.source == "user_hint"
    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.provenance.source == "user_hint"
    assert advice.spin_orbit.enabled is True
    assert advice.pseudopotentials.pseudo_mode == "precision"
    assert advice.pseudopotentials.relativistic_mode == "full"
    assert advice.smearing.smearing_type == "cold"


def test_advise_parameters_uses_analysis_without_silently_enabling_soc() -> None:
    """Flag SOC relevance for heavy elements without enabling it automatically."""
    advice = advise_parameters(
        make_analysis(magnetic_elements=("Fe",), heavy_elements=("I",)),
        intent=CalculationIntent(functional="PBEsol"),
    )

    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.provenance.source == "analysis"
    assert advice.spin_orbit.consider is True
    assert advice.spin_orbit.enabled is False
    assert advice.spin_orbit.provenance.source == "analysis"
    assert advice.pseudopotentials.functional == "PBEsol"
    assert advice.pseudopotentials.relativistic_mode == "scalar"
    assert advice.pseudopotentials.provenance.warnings


def test_advise_parameters_validates_invalid_hints() -> None:
    """Reject invalid hint values before recording them as advice."""
    with pytest.raises(ValueError, match="k_spacing must be positive"):
        advise_parameters(make_analysis(), hints=CalculationHints(k_spacing=0.0))
