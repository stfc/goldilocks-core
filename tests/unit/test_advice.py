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
    electronic_character: str = "unknown",
    dimensionality: str = "unknown",
    has_vacuum: bool = False,
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
        electronic_character=electronic_character,
        dimensionality=dimensionality,
        has_vacuum=has_vacuum,
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
    assert advice.k_points.provenance.reason == (
        "Use the operator-provided explicit k-point grid."
    )
    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.provenance.source == "user_hint"
    assert advice.magnetism.provenance.reason == (
        "Use the operator-provided spin-polarization setting."
    )
    assert advice.spin_orbit.enabled is True
    assert advice.spin_orbit.consider is False
    assert advice.spin_orbit.provenance.reason == (
        "Use the operator-provided SOC setting."
    )
    assert advice.pseudopotentials.pseudo_mode == "precision"
    assert advice.pseudopotentials.relativistic_mode == "full"
    assert advice.smearing.smearing_type == "cold"
    assert advice.smearing.provenance.reason == (
        "Use operator-provided smearing settings."
    )
    assert advice.convergence.provenance.source == "default"
    assert advice.convergence.provenance.reason == (
        "Use package default SCF convergence settings."
    )


def test_advise_parameters_uses_analysis_without_silently_enabling_soc() -> None:
    """Flag SOC relevance for heavy elements without enabling it automatically."""
    advice = advise_parameters(
        make_analysis(magnetic_elements=("Fe",), heavy_elements=("I",)),
        intent=CalculationIntent(functional="PBEsol"),
    )

    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.provenance.source == "analysis"
    assert advice.magnetism.provenance.reason == (
        "Magnetic candidate elements are present in the structure."
    )
    assert advice.spin_orbit.consider is True
    assert advice.spin_orbit.enabled is False
    assert advice.spin_orbit.provenance.source == "analysis"
    assert advice.spin_orbit.provenance.reason == (
        "Period-5-or-heavier elements make SOC worth considering."
    )
    assert advice.pseudopotentials.functional == "PBEsol"
    assert advice.pseudopotentials.relativistic_mode == "scalar"
    assert advice.pseudopotentials.provenance.reason == (
        "Resolve pseudopotential intent from calculation intent and hints."
    )
    assert advice.pseudopotentials.provenance.warnings


@pytest.mark.parametrize(
    "functional",
    ["PBEsol", "PBESOL", "pbe-sol", "PBE_SOL", "PBE sol"],
)
def test_calculation_intent_canonicalizes_supported_pbesol_spellings(
    functional: str,
) -> None:
    """Expose one PBEsol label through Python intent and advice records."""
    intent = CalculationIntent(functional=functional)
    advice = advise_parameters(make_analysis(), intent=intent)

    assert intent.functional == "PBEsol"
    assert advice.pseudopotentials.functional == "PBEsol"


def test_calculation_intent_preserves_unknown_functional_labels() -> None:
    """Do not reinterpret an unknown intent label as PBE."""
    intent = CalculationIntent(functional="RPBE")

    assert intent.functional == "RPBE"


def test_advise_parameters_uses_likely_metal_smearing_from_analysis() -> None:
    """Use analysis-backed smearing only when metallicity is supported."""
    advice = advise_parameters(make_analysis(electronic_character="likely_metal"))

    assert advice.smearing.smearing_type == "cold"
    assert advice.smearing.width_ry == 0.01
    assert advice.smearing.provenance.source == "analysis"
    assert advice.smearing.provenance.reason == (
        "Likely metallic composition benefits from modest smearing."
    )


def test_advise_parameters_records_convergence_hints() -> None:
    """Let operator-provided convergence settings override defaults."""
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(conv_thr=1e-8, mixing_beta=0.2, electron_maxstep=120),
    )

    assert advice.convergence.conv_thr == 1e-8
    assert advice.convergence.mixing_beta == 0.2
    assert advice.convergence.electron_maxstep == 120
    assert advice.convergence.provenance.source == "user_hint"
    assert advice.convergence.provenance.reason == (
        "Use operator-provided convergence settings where supplied."
    )


def test_calculation_hints_validate_before_advice() -> None:
    """Reject invalid hint values at the request contract boundary."""
    with pytest.raises(ValueError, match="CalculationHints.k_spacing"):
        CalculationHints(k_spacing=0.0)

    with pytest.raises(ValueError, match="CalculationHints.conv_thr"):
        CalculationHints(conv_thr=0.0)


def test_advise_parameters_vdw_defaults_off() -> None:
    """Leave vdW off by default for unknown dimensionality."""
    advice = advise_parameters(make_analysis())

    assert advice.vdw.use_vdw is False
    assert advice.vdw.method is None
    assert advice.vdw.provenance.source == "default"


def test_advise_parameters_vdw_hint_enables_default_method() -> None:
    """Enable vdW from a hint and default the method to D3BJ."""
    advice = advise_parameters(make_analysis(), hints=CalculationHints(use_vdw=True))

    assert advice.vdw.use_vdw is True
    assert advice.vdw.method == "d3bj"
    assert advice.vdw.provenance.source == "user_hint"


def test_advise_parameters_vdw_hint_honors_explicit_method() -> None:
    """Honor an explicit vdW method from hints."""
    advice = advise_parameters(
        make_analysis(), hints=CalculationHints(use_vdw=True, vdw_method="ts")
    )

    assert advice.vdw.method == "ts"


def test_advise_parameters_warns_when_vdw_method_set_without_use_vdw() -> None:
    """Warn instead of silently ignoring a vdw_method with no use_vdw flag."""
    advice = advise_parameters(make_analysis(), hints=CalculationHints(vdw_method="ts"))

    assert advice.vdw.use_vdw is False
    assert advice.vdw.method is None
    assert any("was ignored" in w for w in advice.vdw.provenance.warnings)


def test_calculation_hints_reject_unknown_vdw_method() -> None:
    """Reject an unknown vdW method at hint construction."""
    with pytest.raises(ValueError, match="CalculationHints.vdw_method"):
        CalculationHints(vdw_method="xyz")


def test_advise_parameters_enables_vdw_for_low_dimensional_system() -> None:
    """Use D3BJ as a conservative default for the connectivity heuristic."""
    advice = advise_parameters(make_analysis(dimensionality="2d", has_vacuum=True))

    assert advice.vdw.use_vdw is True
    assert advice.vdw.method == "d3bj"
    assert advice.vdw.provenance.source == "analysis"
    assert "Connectivity-derived 2d classification" in advice.vdw.provenance.reason
    assert "dispersion may be important" in advice.vdw.provenance.reason
    assert "Override with CalculationHints" in advice.vdw.provenance.reason


def test_advise_parameters_heuristic_honors_explicit_vdw_method() -> None:
    """Respect an operator vdW method when the heuristic enables vdW."""
    advice = advise_parameters(
        make_analysis(dimensionality="molecule", has_vacuum=True),
        hints=CalculationHints(vdw_method="ts"),
    )

    assert advice.vdw.use_vdw is True
    assert advice.vdw.method == "ts"
    assert advice.vdw.provenance.source == "analysis"
    # Provenance must name the actual method, not a hard-coded D3BJ.
    assert "ts" in advice.vdw.provenance.reason
    assert "D3BJ" not in advice.vdw.provenance.reason


def test_advise_parameters_leaves_vdw_off_for_3d_bulk() -> None:
    """Keep vdW off for fully bonded 3D bulk without an explicit hint."""
    advice = advise_parameters(make_analysis(dimensionality="3d", has_vacuum=False))

    assert advice.vdw.use_vdw is False
    assert advice.vdw.provenance.source == "default"


def test_advise_parameters_hint_overrides_low_dimensional_heuristic() -> None:
    """Let an explicit use_vdw=False override the low-dimensional heuristic."""
    advice = advise_parameters(
        make_analysis(dimensionality="2d", has_vacuum=True),
        hints=CalculationHints(use_vdw=False),
    )

    assert advice.vdw.use_vdw is False
    assert advice.vdw.provenance.source == "user_hint"
