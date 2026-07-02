import numpy as np

from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    CoreJobRequest,
    CoreResult,
    KPointAdvice,
    KPointSelection,
    MagnetismAdvice,
    ParameterAdvice,
    Provenance,
    PseudopotentialAdvice,
    SelectionRecord,
    SmearingAdvice,
    SpinOrbitAdvice,
    StageRecord,
    StructureAnalysisRecord,
    StructureFeatureVector,
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
        k_points=KPointAdvice(
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


def _make_selection() -> SelectionRecord:
    provenance = Provenance(source="default", reason="baseline default")
    return SelectionRecord(
        k_points=KPointSelection(
            grid=(4, 4, 4),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=provenance,
        ),
        pseudopotentials=(),
    )


def test_contracts_serialize_to_json_safe_dicts() -> None:
    """Serialize nested pipeline records without tuples or dataclasses."""
    result = CoreResult(
        intent=CalculationIntent(),
        analysis=_make_analysis(),
        advice=_make_advice(),
        selection=_make_selection(),
        stages=(StageRecord(name="load"), StageRecord(name="analyze")),
    )

    data = result.to_dict()

    assert data["analysis"]["elements"] == ["Si"]
    assert data["selection"]["k_points"]["grid"] == [4, 4, 4]
    assert "grid" not in data
    assert "contains_heavy_elements" not in data


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
        selection=_make_selection(),
        bundle=BundleRecord(path="run/", manifest={"manifest_version": 1}),
        stages=(StageRecord(name="load"), StageRecord(name="analyze")),
    )

    data = result.to_dict()

    assert data["bundle"]["path"] == "run/"
    assert data["stages"][0]["name"] == "load"
    assert data["selection"]["k_points"]["grid"] == [4, 4, 4]


def test_kpoint_advice_requires_exactly_one_k_source() -> None:
    """KPointAdvice raises when both or neither spacing/grid are set."""
    provenance = Provenance(source="default", reason="baseline default")

    KPointAdvice(
        spacing=0.2,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=provenance,
    )
    KPointAdvice(
        spacing=None,
        explicit_grid=(2, 2, 2),
        mesh_type="monkhorst-pack",
        provenance=provenance,
    )

    try:
        KPointAdvice(
            spacing=0.2,
            explicit_grid=(2, 2, 2),
            mesh_type="monkhorst-pack",
            provenance=provenance,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for both spacing and grid")

    try:
        KPointAdvice(
            spacing=None,
            explicit_grid=None,
            mesh_type="monkhorst-pack",
            provenance=provenance,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for neither spacing nor grid")


def test_core_job_request_validates_mode_and_bundle_output_dir() -> None:
    """CoreJobRequest raises at construction for invalid mode or missing output_dir."""
    CoreJobRequest(structure="Si.cif", mode="recommend")
    CoreJobRequest(structure="Si.cif", mode="generate")
    CoreJobRequest(structure="Si.cif", mode="bundle", output_dir="run/")

    try:
        CoreJobRequest(structure="Si.cif", mode="invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid mode")

    try:
        CoreJobRequest(structure="Si.cif", mode="bundle")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for bundle mode without output_dir")
