import json
from pathlib import Path

import pytest

from goldilocks_core.advice import advise_parameters
from goldilocks_core.bundle import build_bundle_manifest, write_bundle_directory
from goldilocks_core.contracts import (
    CalculationIntent,
    CoreRecommendation,
    GeneratedFile,
    KPointSelection,
    Provenance,
    SelectionRecord,
    StructureAnalysisRecord,
)


def make_recommendation() -> CoreRecommendation:
    """Build a minimal recommendation with one generated file."""
    analysis = StructureAnalysisRecord(
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
    advice = advise_parameters(analysis)
    selection = SelectionRecord(
        k_points=KPointSelection(
            grid=(4, 4, 4),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="default", reason="test"),
        ),
        pseudopotentials=(),
    )
    return CoreRecommendation(
        intent=CalculationIntent(),
        analysis=analysis,
        advice=advice,
        selection=selection,
        generated_files=(GeneratedFile(path="inputs/qe.in", content="&CONTROL\n/\n"),),
        warnings=("test warning",),
    )


def test_build_bundle_manifest_records_file_metadata_without_content() -> None:
    """Build a manifest containing stage outputs and generated file metadata."""
    manifest = build_bundle_manifest(make_recommendation())

    assert manifest["manifest_version"] == 1
    assert manifest["intent"]["code"] == "quantum_espresso"
    assert manifest["analysis"]["elements"] == ["Si"]
    assert manifest["advice"]["k_points"]["mesh_type"] == "monkhorst-pack"
    assert manifest["selection"]["k_points"]["grid"] == [4, 4, 4]
    assert manifest["generated_files"] == [
        {"path": "inputs/qe.in", "role": "input", "bytes": 11}
    ]
    assert manifest["warnings"] == ["test warning"]


def test_write_bundle_directory_writes_manifest_and_files(tmp_path: Path) -> None:
    """Write a deterministic bundle layout to disk."""
    recommendation = make_recommendation()

    manifest = write_bundle_directory(recommendation, tmp_path)

    assert (
        tmp_path / "inputs" / "qe.in"
    ).read_text(encoding="utf-8") == "&CONTROL\n/\n"
    manifest_data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_data == manifest
    assert manifest_data["generated_files"][0]["path"] == "inputs/qe.in"


def test_write_bundle_directory_rejects_path_traversal(tmp_path: Path) -> None:
    """Reject generated file paths that escape the bundle directory."""
    recommendation = make_recommendation()
    recommendation = CoreRecommendation(
        intent=recommendation.intent,
        analysis=recommendation.analysis,
        advice=recommendation.advice,
        selection=recommendation.selection,
        generated_files=(GeneratedFile(path="../qe.in", content="bad"),),
    )

    with pytest.raises(ValueError, match="escapes bundle directory"):
        write_bundle_directory(recommendation, tmp_path)
