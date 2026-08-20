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
    low_dimensional: bool = False,
) -> StructureAnalysisRecord:
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
        low_dimensional=low_dimensional,
    )


def test_advise_parameters_records_user_hint_provenance() -> None:
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(
            k_grid=(2, 2, 1),
            spin_polarized=True,
            spin_orbit_coupling=True,
            pseudo_accuracy="precision",
            smearing_type="cold",
            smearing_width_ry=0.01,
        ),
    )

    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.provenance.source == "user_hint"
    assert advice.spin_orbit.enabled is True
    assert advice.spin_orbit.consider is False
    assert advice.pseudopotential_requirements.accuracy == "precision"
    assert advice.pseudopotential_requirements.relativistic == "full"
    assert advice.smearing.smearing_type == "cold"
    assert advice.convergence.provenance.source == "default"


def test_advise_parameters_uses_analysis_without_silently_enabling_soc() -> None:
    advice = advise_parameters(
        make_analysis(magnetic_elements=("Fe",), heavy_elements=("I",)),
        intent=CalculationIntent(functional="PBEsol"),
    )

    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.provenance.source == "analysis"
    assert advice.spin_orbit.consider is True
    assert advice.spin_orbit.enabled is False
    assert advice.spin_orbit.provenance.source == "analysis"
    assert advice.spin_orbit.heavy_elements == ("I",)
    assert advice.pseudopotential_requirements.functional == "PBEsol"
    assert advice.pseudopotential_requirements.relativistic == "scalar"
    assert advice.pseudopotential_requirements.provenance.warnings


@pytest.mark.parametrize(
    "functional",
    ["PBEsol", "PBESOL", "pbe-sol", "PBE_SOL", "PBE sol"],
)
def test_calculation_intent_canonicalizes_supported_pbesol_spellings(
    functional: str,
) -> None:
    intent = CalculationIntent(functional=functional)
    advice = advise_parameters(make_analysis(), intent=intent)

    assert intent.functional == "PBEsol"
    assert advice.pseudopotential_requirements.functional == "PBEsol"


def test_calculation_intent_preserves_unknown_functional_labels() -> None:
    intent = CalculationIntent(functional="RPBE")

    assert intent.functional == "RPBE"


def test_advise_parameters_uses_likely_metal_smearing_from_analysis() -> None:
    advice = advise_parameters(make_analysis(electronic_character="likely_metal"))

    assert advice.smearing.smearing_type == "cold"
    assert advice.smearing.width_ry == 0.01
    assert advice.smearing.provenance.source == "analysis"


def test_advise_parameters_uses_metal_smearing_from_ml_classification() -> None:
    advice = advise_parameters(make_analysis(electronic_character="metal"))

    assert advice.smearing.smearing_type == "cold"
    assert advice.smearing.width_ry == 0.01
    assert advice.smearing.provenance.source == "analysis"


def test_advise_smearing_records_user_hint_provenance_when_hinted() -> None:
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(smearing_type="gaussian", smearing_width_ry=0.02),
    )

    assert advice.smearing.smearing_type == "gaussian"
    assert advice.smearing.width_ry == 0.02
    assert advice.smearing.provenance.source == "user_hint"


def test_advise_smearing_defaults_to_fixed_occupations_for_non_metals() -> None:
    advice = advise_parameters(make_analysis(electronic_character="insulator"))

    assert advice.smearing.smearing_type == "fixed"
    assert advice.smearing.width_ry is None
    assert advice.smearing.provenance.source == "default"


def test_advise_spin_orbit_user_hint_records_provenance_and_heavy_elements() -> None:
    advice = advise_parameters(
        make_analysis(heavy_elements=("I",)),
        hints=CalculationHints(spin_orbit_coupling=True),
    )

    assert advice.spin_orbit.enabled is True
    assert advice.spin_orbit.consider is False
    assert advice.spin_orbit.heavy_elements == ("I",)
    assert advice.spin_orbit.provenance.source == "user_hint"


def test_advise_spin_orbit_defaults_to_disabled_without_heavy_elements() -> None:
    advice = advise_parameters(make_analysis())

    assert advice.spin_orbit.enabled is False
    assert advice.spin_orbit.consider is False
    assert advice.spin_orbit.heavy_elements == ()
    assert advice.spin_orbit.provenance.source == "default"


def test_advise_pseudo_requirements_records_user_hint_source_without_soc() -> None:
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(pseudo_accuracy="precision"),
    )

    requirements = advice.pseudopotential_requirements
    assert requirements.provenance.source == "user_hint"
    assert requirements.provenance.warnings == ()


def test_advise_pseudo_requirements_records_default_source_without_hints() -> None:
    advice = advise_parameters(make_analysis())

    requirements = advice.pseudopotential_requirements
    assert requirements.provenance.source == "default"
    assert requirements.provenance.warnings == ()


def test_advise_pseudo_requirements_records_analysis_source_for_soc() -> None:
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(spin_orbit_coupling=True),
    )

    requirements = advice.pseudopotential_requirements
    assert requirements.provenance.source == "analysis"
    assert requirements.relativistic == "full"


def test_advise_magnetism_user_hint_carries_magnetic_elements() -> None:
    advice = advise_parameters(
        make_analysis(magnetic_elements=("Fe",)),
        hints=CalculationHints(spin_polarized=True),
    )

    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.magnetic_elements == ("Fe",)
    assert advice.magnetism.provenance.source == "user_hint"


def test_advise_magnetism_analysis_carries_magnetic_elements() -> None:
    advice = advise_parameters(make_analysis(magnetic_elements=("Fe",)))

    assert advice.magnetism.spin_polarized is True
    assert advice.magnetism.magnetic_elements == ("Fe",)
    assert advice.magnetism.provenance.source == "analysis"


def test_advise_magnetism_defaults_without_magnetic_elements() -> None:
    advice = advise_parameters(make_analysis())

    assert advice.magnetism.spin_polarized is False
    assert advice.magnetism.magnetic_elements == ()
    assert advice.magnetism.provenance.source == "default"


def test_advise_parameters_records_convergence_hints() -> None:
    advice = advise_parameters(
        make_analysis(),
        hints=CalculationHints(conv_thr=1e-8, mixing_beta=0.2, electron_maxstep=120),
    )

    assert advice.convergence.conv_thr == 1e-8
    assert advice.convergence.mixing_beta == 0.2
    assert advice.convergence.electron_maxstep == 120
    assert advice.convergence.provenance.source == "user_hint"


def test_calculation_hints_validate_before_advice() -> None:
    with pytest.raises(ValueError, match="CalculationHints.k_spacing"):
        CalculationHints(k_spacing=0.0)

    with pytest.raises(ValueError, match="CalculationHints.conv_thr"):
        CalculationHints(conv_thr=0.0)


def test_calculation_hints_validate_pseudo_fields() -> None:
    with pytest.raises(ValueError, match="relativistic_mode"):
        CalculationHints(relativistic_mode="garbage")

    with pytest.raises(ValueError, match="pseudo_accuracy"):
        CalculationHints(pseudo_accuracy="")

    with pytest.raises(ValueError, match="pseudo_type"):
        CalculationHints(pseudo_type="   ")


def test_calculation_intent_validates_pseudo_accuracy() -> None:
    with pytest.raises(ValueError, match="pseudo_accuracy"):
        CalculationIntent(pseudo_accuracy="fast")


def test_advise_parameters_vdw_defaults_off() -> None:
    advice = advise_parameters(make_analysis())

    assert advice.vdw.use_vdw is False
    assert advice.vdw.method is None
    assert advice.vdw.provenance.source == "default"


def test_advise_parameters_vdw_hint_enables_default_method() -> None:
    advice = advise_parameters(make_analysis(), hints=CalculationHints(use_vdw=True))

    assert advice.vdw.use_vdw is True
    assert advice.vdw.method == "d3bj"
    assert advice.vdw.provenance.source == "user_hint"


def test_advise_parameters_vdw_hint_honors_explicit_method() -> None:
    advice = advise_parameters(
        make_analysis(), hints=CalculationHints(use_vdw=True, vdw_method="ts")
    )

    assert advice.vdw.method == "ts"


def test_advise_parameters_warns_when_vdw_method_set_without_use_vdw() -> None:
    advice = advise_parameters(make_analysis(), hints=CalculationHints(vdw_method="ts"))

    assert advice.vdw.use_vdw is False
    assert advice.vdw.method is None
    assert any("was ignored" in w for w in advice.vdw.provenance.warnings)


def test_calculation_hints_reject_unknown_vdw_method() -> None:
    with pytest.raises(ValueError, match="CalculationHints.vdw_method"):
        CalculationHints(vdw_method="xyz")


def test_advise_parameters_enables_vdw_for_low_dimensional_system() -> None:
    advice = advise_parameters(make_analysis(dimensionality="2d", low_dimensional=True))

    assert advice.vdw.use_vdw is True
    assert advice.vdw.method == "d3bj"
    assert advice.vdw.provenance.source == "analysis"
    assert "Low-dimensional 2d" in advice.vdw.provenance.reason
    assert "dispersion may be important" in advice.vdw.provenance.reason


def test_advise_parameters_heuristic_honors_explicit_vdw_method() -> None:
    advice = advise_parameters(
        make_analysis(dimensionality="molecule", low_dimensional=True),
        hints=CalculationHints(vdw_method="ts"),
    )

    assert advice.vdw.use_vdw is True
    assert advice.vdw.method == "ts"
    assert advice.vdw.provenance.source == "analysis"
    # Provenance must name the actual method, not a hard-coded D3BJ.
    assert "ts" in advice.vdw.provenance.reason
    assert "D3BJ" not in advice.vdw.provenance.reason


def test_advise_parameters_leaves_vdw_off_for_3d_bulk() -> None:
    advice = advise_parameters(
        make_analysis(dimensionality="3d", low_dimensional=False)
    )

    assert advice.vdw.use_vdw is False
    assert advice.vdw.provenance.source == "default"


def test_advise_parameters_hint_overrides_low_dimensional_heuristic() -> None:
    advice = advise_parameters(
        make_analysis(dimensionality="2d", low_dimensional=True),
        hints=CalculationHints(use_vdw=False),
    )

    assert advice.vdw.use_vdw is False
    assert advice.vdw.provenance.source == "user_hint"
