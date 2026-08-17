import numpy as np
import pytest

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    KPointSelection,
    MagnetismAdvice,
    ParameterAdvice,
    PresetRequest,
    Provenance,
    PseudopotentialRequirements,
    Records,
    Result,
    SelectionRecord,
    SmearingAdvice,
    SpinOrbitAdvice,
    StructureAnalysisRecord,
    StructureFeatureVector,
    VdwAdvice,
)


def _make_analysis() -> StructureAnalysisRecord:
    return StructureAnalysisRecord(
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
    )


def _make_advice() -> ParameterAdvice:
    provenance = Provenance(source="default", reason="baseline default")
    return ParameterAdvice(
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
        pseudopotential_requirements=PseudopotentialRequirements(
            functional="PBE",
            accuracy="efficiency",
            pseudo_type=None,
            relativistic="scalar",
            provenance=provenance,
        ),
        convergence=ConvergenceAdvice(conv_thr=1e-6, provenance=provenance),
        vdw=VdwAdvice(use_vdw=False, method=None, provenance=provenance),
    )


def _make_k_points() -> KPointSelection:
    provenance = Provenance(source="default", reason="baseline default")
    return KPointSelection(
        grid=(4, 4, 4),
        shift=(0, 0, 0),
        mesh_type="monkhorst-pack",
        provenance=provenance,
    )


def _make_selection() -> SelectionRecord:
    return SelectionRecord(pseudopotentials=())


def test_contracts_serialize_to_json_safe_dicts() -> None:
    """Serialize nested pipeline records without tuples or dataclasses."""
    result = Result(
        intent=CalculationIntent(),
        analysis=_make_analysis(),
        advice=_make_advice(),
        k_points=_make_k_points(),
        selection=_make_selection(),
    )

    data = result.to_dict()

    assert data["analysis"]["elements"] == ["Si"]
    assert data["k_points"]["grid"] == [4, 4, 4]
    assert "grid" not in data
    assert "contains_heavy_elements" not in data


def test_core_records_maps_requested_types_and_serializes_record_names() -> None:
    """Expose only requested DAG records and serialize their stable ids."""
    analysis = _make_analysis()
    records = Records({StructureAnalysisRecord: analysis})

    assert records[StructureAnalysisRecord] is analysis
    assert tuple(records) == (StructureAnalysisRecord,)
    assert records.to_dict() == {
        "analysis": analysis.to_dict(),
    }


def test_calculation_intent_validates_pseudo_accuracy() -> None:
    """Expose one typed registered accuracy tier in intent."""
    assert CalculationIntent(pseudo_accuracy="precision").pseudo_accuracy == "precision"
    with pytest.raises(ValueError, match="pseudo_accuracy"):
        CalculationIntent(pseudo_accuracy="fast")


def test_hints_serialize_explicit_grid_as_list() -> None:
    """Serialize optional hints for API and CLI JSON callers."""
    data = CalculationHints(k_grid=(2, 2, 1)).to_dict()

    assert data["k_grid"] == [2, 2, 1]


def test_calculation_hints_expose_per_stage_views() -> None:
    """CalculationHints decomposes into one narrow hint view per stage."""
    hints = CalculationHints(
        k_grid=(2, 2, 1),
        k_spacing=0.25,
        smearing_type="cold",
        smearing_width_ry=0.01,
        spin_polarized=True,
        spin_orbit_coupling=False,
        pseudo_accuracy="precision",
        pseudo_type="NC",
        relativistic_mode="full",
        conv_thr=1e-8,
        mixing_beta=0.2,
        electron_maxstep=120,
        use_vdw=True,
        vdw_method="ts",
    )

    assert hints.kmesh.k_grid == (2, 2, 1)
    assert hints.kmesh.k_spacing == 0.25
    assert hints.smearing.smearing_type == "cold"
    assert hints.smearing.smearing_width_ry == 0.01
    assert hints.spin.spin_polarized is True
    assert hints.spin.spin_orbit_coupling is False
    assert hints.pseudo.accuracy == "precision"
    assert hints.pseudo.pseudo_type == "NC"
    assert hints.pseudo.relativistic_mode == "full"
    assert hints.convergence.conv_thr == 1e-8
    assert hints.convergence.mixing_beta == 0.2
    assert hints.convergence.electron_maxstep == 120
    assert hints.vdw.use_vdw is True
    assert hints.vdw.vdw_method == "ts"


def test_feature_vectors_serialize_numpy_values_as_json_lists() -> None:
    """Convert NumPy arrays and scalars to JSON-safe values."""
    data = StructureFeatureVector(
        values=np.array([1.0, 2.0]),
        feature_names=["a", "b"],
    ).to_dict()

    assert data["values"] == [1.0, 2.0]


def test_job_records_serialize_to_json_safe_dicts() -> None:
    """Serialize job result records for CLI and future HTTP callers."""
    result = Result(
        intent=CalculationIntent(),
        analysis=_make_analysis(),
        advice=_make_advice(),
        k_points=_make_k_points(),
        selection=_make_selection(),
        bundle=BundleRecord(path="run/", manifest={"manifest_version": 2}),
    )

    data = result.to_dict()

    assert data["bundle"]["path"] == "run/"
    assert data["k_points"]["grid"] == [4, 4, 4]


def test_preset_request_validates_mode() -> None:
    """PresetRequest raises at construction for invalid modes."""
    PresetRequest(structure="Si.cif", mode="recommend")
    PresetRequest(structure="Si.cif", mode="generate")

    try:
        PresetRequest(structure="Si.cif", mode="invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid mode")


def test_calculation_intent_defaults_to_pbesol() -> None:
    """Pin the default functional: changing it changes every generated input."""
    assert CalculationIntent().functional == "PBEsol"
