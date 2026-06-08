from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreRecommendation,
    ConvergenceAdvice,
    KPointAdviceRecord,
    KPointSelection,
    MagnetismAdvice,
    ParameterAdvice,
    Provenance,
    PseudopotentialAdvice,
    SelectionRecord,
    SmearingAdvice,
    SpinOrbitAdvice,
    StructureAnalysisRecord,
)


def test_contracts_serialize_to_json_safe_dicts() -> None:
    """Serialize nested pipeline records without tuples or dataclasses."""
    provenance = Provenance(source="default", reason="baseline default")
    advice = ParameterAdvice(
        k_points=KPointAdviceRecord(
            spacing=0.2,
            explicit_grid=None,
            mesh_type="monkhorst-pack",
            provenance=provenance,
        ),
        smearing=SmearingAdvice(
            smearing_type=None,
            width_ry=None,
            provenance=provenance,
        ),
        magnetism=MagnetismAdvice(
            spin_polarized=False,
            magnetic_elements=(),
            provenance=provenance,
        ),
        spin_orbit=SpinOrbitAdvice(
            enabled=False,
            consider=False,
            heavy_elements=(),
            provenance=provenance,
        ),
        pseudopotentials=PseudopotentialAdvice(
            functional="PBE",
            pseudo_mode="efficiency",
            pseudo_type=None,
            relativistic_mode="scalar",
            provenance=provenance,
        ),
        convergence=ConvergenceAdvice(conv_thr=1e-6, provenance=provenance),
    )
    recommendation = CoreRecommendation(
        intent=CalculationIntent(),
        analysis=StructureAnalysisRecord(
            formula="Si1",
            reduced_formula="Si",
            site_count=1,
            elements=("Si",),
            contains_transition_metals=False,
            contains_lanthanides=False,
            contains_actinides=False,
            contains_heavy_elements=False,
            magnetic_elements=(),
            heavy_elements=(),
        ),
        advice=advice,
        selection=SelectionRecord(
            k_points=KPointSelection(
                grid=(4, 4, 4),
                shift=(0, 0, 0),
                mesh_type="monkhorst-pack",
                provenance=provenance,
            ),
            pseudopotentials=(),
        ),
    )

    data = recommendation.to_dict()

    assert data["analysis"]["elements"] == ["Si"]
    assert data["selection"]["k_points"]["grid"] == [4, 4, 4]
    assert data["grid"] == [4, 4, 4]
    assert data["contains_heavy_elements"] is False


def test_hints_serialize_explicit_grid_as_list() -> None:
    """Serialize optional hints for API and CLI JSON callers."""
    data = CalculationHints(k_grid=(2, 2, 1)).to_dict()

    assert data["k_grid"] == [2, 2, 1]
