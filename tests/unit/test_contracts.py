import numpy as np
import pytest

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    CoreJobRequest,
    CoreRecords,
    CoreResult,
    KPointSelection,
    MagnetismAdvice,
    ParameterAdvice,
    Provenance,
    PseudopotentialAdvice,
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
        pseudopotentials=PseudopotentialAdvice(
            functional="PBE",
            pseudo_mode="efficiency",
            pseudo_type=None,
            relativistic_mode="scalar",
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
    result = CoreResult(
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
    """Expose only requested DAG records and serialize their type names."""
    analysis = _make_analysis()
    records = CoreRecords({StructureAnalysisRecord: analysis})

    assert records[StructureAnalysisRecord] is analysis
    assert tuple(records) == (StructureAnalysisRecord,)
    assert records.to_dict() == {
        "StructureAnalysisRecord": analysis.to_dict(),
    }


def test_calculation_intent_omits_removed_accuracy_control() -> None:
    """Keep unsupported accuracy semantics out of construction and serialization."""
    with pytest.raises(TypeError, match="accuracy_level"):
        CalculationIntent(accuracy_level="high")

    assert "accuracy_level" not in CalculationIntent().to_dict()


def test_hints_serialize_explicit_grid_as_list() -> None:
    """Serialize optional hints for API and CLI JSON callers."""
    data = CalculationHints(k_grid=(2, 2, 1)).to_dict()

    assert data["k_grid"] == [2, 2, 1]


def test_feature_vectors_serialize_numpy_values_as_json_lists() -> None:
    """Convert NumPy arrays and scalars to JSON-safe values."""
    data = StructureFeatureVector(
        values=np.array([1.0, 2.0]),
        feature_names=["a", "b"],
    ).to_dict()

    assert data["values"] == [1.0, 2.0]


def test_job_records_serialize_to_json_safe_dicts() -> None:
    """Serialize job result records for CLI and future HTTP callers."""
    result = CoreResult(
        intent=CalculationIntent(),
        analysis=_make_analysis(),
        advice=_make_advice(),
        k_points=_make_k_points(),
        selection=_make_selection(),
        bundle=BundleRecord(path="run/", manifest={"manifest_version": 1}),
    )

    data = result.to_dict()

    assert data["bundle"]["path"] == "run/"
    assert data["k_points"]["grid"] == [4, 4, 4]


def test_core_job_request_validates_mode() -> None:
    """CoreJobRequest raises at construction for invalid modes."""
    CoreJobRequest(structure="Si.cif", mode="recommend")
    CoreJobRequest(structure="Si.cif", mode="generate")

    try:
        CoreJobRequest(structure="Si.cif", mode="invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid mode")


def test_calculation_intent_defaults_to_pbesol() -> None:
    """Pin the default functional: changing it changes every generated input."""
    assert CalculationIntent().functional == "PBEsol"
