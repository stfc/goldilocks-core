import numpy as np
import pytest

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


def _make_advice(provenance: Provenance) -> ParameterAdvice:
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


def _make_selection(provenance: Provenance) -> SelectionRecord:
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
    provenance = Provenance(source="default", reason="baseline default")
    result = CoreResult(
        intent=CalculationIntent(),
        analysis=_make_analysis(),
        advice=_make_advice(provenance),
        selection=_make_selection(provenance),
    )

    data = result.to_dict()

    assert data["analysis"]["elements"] == ["Si"]
    assert data["selection"]["k_points"]["grid"] == [4, 4, 4]
    assert "grid" not in data
    assert "contains_heavy_elements" not in data
    # request is not echoed on CoreResult
    assert "request" not in data


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


def test_core_result_serializes_with_stages_and_bundle() -> None:
    """Serialize CoreResult with execution trace and bundle record."""
    provenance = Provenance(source="default", reason="baseline default")
    result = CoreResult(
        intent=CalculationIntent(),
        analysis=_make_analysis(),
        advice=_make_advice(provenance),
        selection=_make_selection(provenance),
        generated_files=(),
        warnings=("a warning",),
        bundle=BundleRecord(path="run/", manifest={"manifest_version": 1}),
        stages=(StageRecord(name="load"), StageRecord(name="analyze")),
    )

    data = result.to_dict()

    assert data["stages"][0]["name"] == "load"
    assert data["selection"]["k_points"]["grid"] == [4, 4, 4]
    assert data["bundle"]["path"] == "run/"
    assert data["bundle"]["manifest"]["manifest_version"] == 1
    assert data["warnings"] == ["a warning"]


def test_kpoint_advice_requires_exactly_one_of_spacing_or_grid() -> None:
    """KPointAdvice raises at construction unless exactly one input is set."""
    provenance = Provenance(source="default", reason="baseline default")
    # exactly one (spacing) is fine
    KPointAdvice(spacing=0.2, explicit_grid=None, mesh_type="mp", provenance=provenance)
    # exactly one (grid) is fine
    KPointAdvice(
        spacing=None, explicit_grid=(4, 4, 4), mesh_type="mp", provenance=provenance
    )

    with pytest.raises(ValueError, match="exactly one"):
        KPointAdvice(
            spacing=None, explicit_grid=None, mesh_type="mp", provenance=provenance
        )
    with pytest.raises(ValueError, match="exactly one"):
        KPointAdvice(
            spacing=0.2,
            explicit_grid=(4, 4, 4),
            mesh_type="mp",
            provenance=provenance,
        )


def test_core_job_request_validates_mode_and_output_dir() -> None:
    """CoreJobRequest raises at construction for invalid mode or missing output_dir."""
    # valid modes
    CoreJobRequest(structure="Si.cif", mode="recommend")
    CoreJobRequest(structure="Si.cif", mode="generate")
    CoreJobRequest(structure="Si.cif", mode="bundle", output_dir="run/")

    with pytest.raises(ValueError, match="output_dir is required"):
        CoreJobRequest(structure="Si.cif", mode="bundle")

    with pytest.raises(ValueError, match="Unsupported Core job mode"):
        CoreJobRequest(structure="Si.cif", mode="bogus")  # type: ignore[arg-type]
