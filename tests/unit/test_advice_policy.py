from __future__ import annotations

import pytest

from goldilocks_core.advice.magnetism import MagnetismAdvice, advise_magnetism
from goldilocks_core.advice.smearing import SmearingAdvice, advise_smearing
from goldilocks_core.advice.soc import SpinOrbitAdvice, advise_spin_orbit
from goldilocks_core.advice.vdw import VdwAdvice, advise_vdw
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import SmearingHints, SpinHints, VdwHints
from goldilocks_core.provenance import Provenance


def analysis(
    *,
    electronic_character: str = "unknown",
    electronic_character_source: str = "heuristic",
    magnetic_elements: tuple[str, ...] = (),
    heavy_elements: tuple[str, ...] = (),
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
        electronic_character_source=electronic_character_source,
        dimensionality=dimensionality,
        low_dimensional=low_dimensional,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_soc_operator_choice_is_complete_and_never_adds_consideration(
    enabled: bool,
) -> None:
    assert advise_spin_orbit(
        analysis(heavy_elements=("I",)),
        SpinHints(spin_orbit_coupling=enabled),
    ) == SpinOrbitAdvice(
        enabled=enabled,
        consider=False,
        heavy_elements=("I",),
        provenance=Provenance(
            source="user_hint",
            reason="Use the operator-provided SOC setting.",
        ),
    )


def test_soc_heavy_element_advice_preserves_cost_warning() -> None:
    assert advise_spin_orbit(
        analysis(heavy_elements=("I",)), SpinHints()
    ) == SpinOrbitAdvice(
        enabled=False,
        consider=True,
        heavy_elements=("I",),
        provenance=Provenance(
            source="analysis",
            reason="Period-5-or-heavier elements make SOC worth considering.",
            warnings=(
                "SOC is not enabled automatically because it changes cost and setup.",
            ),
        ),
    )


def test_soc_default_records_absence_of_heavy_elements() -> None:
    assert advise_spin_orbit(analysis(), SpinHints()) == SpinOrbitAdvice(
        enabled=False,
        consider=False,
        heavy_elements=(),
        provenance=Provenance(
            source="default",
            reason="No period-5-or-heavier elements were detected.",
        ),
    )


def test_smearing_operator_choice_is_preserved_exactly() -> None:
    assert advise_smearing(
        analysis(), SmearingHints(smearing_type="gaussian", smearing_width_ry=0.02)
    ) == SmearingAdvice(
        smearing_type="gaussian",
        width_ry=0.02,
        provenance=Provenance(
            source="user_hint",
            reason="Use operator-provided smearing settings.",
        ),
    )


def test_model_classified_metal_uses_smearing_without_a_heuristic_warning() -> None:
    assert advise_smearing(
        analysis(electronic_character="metal", electronic_character_source="model"),
        SmearingHints(),
    ) == SmearingAdvice(
        smearing_type="cold",
        width_ry=0.01,
        provenance=Provenance(
            source="analysis",
            reason="Model-classified metallic systems benefit from modest smearing.",
        ),
    )


def test_heuristic_metallicity_keeps_its_uncertainty_warning() -> None:
    assert advise_smearing(
        analysis(electronic_character="likely_metal"), SmearingHints()
    ) == SmearingAdvice(
        smearing_type="cold",
        width_ry=0.01,
        provenance=Provenance(
            source="analysis",
            reason="Likely metallic composition benefits from modest smearing.",
            warnings=("Metallicity was inferred from structure-only heuristics.",),
        ),
    )


def test_model_classified_insulator_uses_analysis_backed_fixed_occupations() -> None:
    assert advise_smearing(
        analysis(electronic_character="insulator", electronic_character_source="model"),
        SmearingHints(),
    ) == SmearingAdvice(
        smearing_type="fixed",
        width_ry=None,
        provenance=Provenance(
            source="analysis",
            reason="Insulating electronic character supports fixed occupations.",
        ),
    )


def test_unknown_metallicity_defaults_to_fixed_occupations() -> None:
    assert advise_smearing(analysis(), SmearingHints()) == SmearingAdvice(
        smearing_type="fixed",
        width_ry=None,
        provenance=Provenance(
            source="default",
            reason="Metallicity is unknown; use fixed occupations by default.",
        ),
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_magnetism_operator_choice_preserves_candidates(enabled: bool) -> None:
    assert advise_magnetism(
        analysis(magnetic_elements=("Fe",)), SpinHints(spin_polarized=enabled)
    ) == MagnetismAdvice(
        spin_polarized=enabled,
        magnetic_elements=("Fe",),
        provenance=Provenance(
            source="user_hint",
            reason="Use the operator-provided spin-polarization setting.",
        ),
    )


def test_magnetism_analysis_enables_spin_for_candidate_elements() -> None:
    assert advise_magnetism(
        analysis(magnetic_elements=("Fe",)), SpinHints()
    ) == MagnetismAdvice(
        spin_polarized=True,
        magnetic_elements=("Fe",),
        provenance=Provenance(
            source="analysis",
            reason="Magnetic candidate elements are present in the structure.",
        ),
    )


def test_magnetism_default_records_absence_of_candidates() -> None:
    assert advise_magnetism(analysis(), SpinHints()) == MagnetismAdvice(
        spin_polarized=False,
        magnetic_elements=(),
        provenance=Provenance(
            source="default",
            reason="No magnetic candidate elements were detected.",
        ),
    )


@pytest.mark.parametrize("method", [None, "ts"])
def test_low_dimensional_vdw_advice_records_resolved_method(
    method: str | None,
) -> None:
    expected_method = "d3bj" if method is None else method
    reason = (
        "Connectivity-derived 2d classification indicates a low-dimensional heuristic; "
        "D3BJ is the conservative package default because dispersion may be "
        "important. Override with CalculationHints(use_vdw=..., vdw_method=...) "
        "as needed."
        if method is None
        else "Connectivity-derived 2d classification indicates a low-dimensional "
        "heuristic; use the operator-provided ts vdW method. Override with "
        "CalculationHints(use_vdw=...) as needed."
    )
    assert advise_vdw(
        analysis(dimensionality="2d", low_dimensional=True),
        VdwHints(vdw_method=method),
    ) == VdwAdvice(
        use_vdw=True,
        method=expected_method,
        provenance=Provenance(source="analysis", reason=reason),
    )


@pytest.mark.parametrize("enabled, method", [(False, None), (True, "d3bj")])
def test_vdw_operator_switch_overrides_structure_analysis(
    enabled: bool,
    method: str | None,
) -> None:
    assert advise_vdw(
        analysis(dimensionality="2d", low_dimensional=True),
        VdwHints(use_vdw=enabled),
    ) == VdwAdvice(
        use_vdw=enabled,
        method=method,
        provenance=Provenance(
            source="user_hint",
            reason="Use the operator-provided vdW dispersion setting.",
        ),
    )


def test_vdw_method_without_enablement_is_rejected_by_provenance_warning() -> None:
    assert advise_vdw(analysis(), VdwHints(vdw_method="ts")) == VdwAdvice(
        use_vdw=False,
        method=None,
        provenance=Provenance(
            source="default",
            reason=(
                "3D bulk or undetermined dimensionality; no vdW correction by "
                "default. Set use_vdw=True for layered or molecular systems."
            ),
            warnings=(
                "vdw_method='ts' was ignored because vdW is off for this "
                "3D/undetermined system; pass use_vdw=True to force it.",
            ),
        ),
    )
