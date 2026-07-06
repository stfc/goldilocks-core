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
    assert advice.convergence.provenance.source == "default"


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


def test_advise_parameters_uses_likely_metal_smearing_from_analysis() -> None:
    """Use analysis-backed smearing only when metallicity is supported."""
    advice = advise_parameters(make_analysis(electronic_character="likely_metal"))

    assert advice.smearing.smearing_type == "cold"
    assert advice.smearing.width_ry == 0.01
    assert advice.smearing.provenance.source == "analysis"


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


def test_advise_parameters_validates_invalid_hints() -> None:
    """Reject invalid hint values before recording them as advice."""
    with pytest.raises(ValueError, match="k_spacing must be positive"):
        advise_parameters(make_analysis(), hints=CalculationHints(k_spacing=0.0))

    with pytest.raises(ValueError, match="conv_thr must be positive"):
        advise_parameters(make_analysis(), hints=CalculationHints(conv_thr=0.0))


def test_advise_parameters_vdw_defaults_off() -> None:
    """Leave vdW off by default until dimensionality detection lands."""
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


def test_advise_parameters_rejects_unknown_vdw_method() -> None:
    """Reject an unknown vdW method before recording it as advice."""
    with pytest.raises(ValueError, match="Unknown vdw_method"):
        advise_parameters(make_analysis(), hints=CalculationHints(vdw_method="xyz"))
