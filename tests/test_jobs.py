import json
from pathlib import Path

from pymatgen.core import Lattice, Structure

from goldilocks_core import CalculationHints, CoreJobRequest, run_core_job
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata with cutoffs."""
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        library="SSSP",
        element="Si",
        pseudo_type="NC",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )


def test_run_core_job_recommend_matches_public_recommendation_shape() -> None:
    """Run the fixed job graph through Select for recommendation mode."""
    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        )
    )

    assert [stage.name for stage in result.stages] == [
        "load",
        "analyze",
        "advise",
        "select",
    ]
    assert result.recommendation.selection.k_points.grid == (2, 2, 1)
    assert result.recommendation.selection.pseudopotentials[0].filename == "Si.UPF"
    assert result.generated_files == ()
    assert result.bundle_path is None


def test_run_core_job_generate_adds_generated_files() -> None:
    """Run the fixed job graph through Generate for generated files."""
    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="generate",
        )
    )

    assert [stage.name for stage in result.stages][-1] == "generate"
    assert result.generated_files[0].path == "inputs/qe.in"
    assert "2  2  1  0  0  0" in result.generated_files[0].content


def test_run_core_job_bundle_writes_output_directory(tmp_path: Path) -> None:
    """Run the fixed job graph through Bundle and write files."""
    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="bundle",
            output_dir=str(tmp_path),
        )
    )

    assert [stage.name for stage in result.stages][-1] == "bundle"
    assert result.bundle_path == str(tmp_path)
    assert (tmp_path / "inputs" / "qe.in").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["selection"]["k_points"]["grid"] == [2, 2, 1]
    assert result.manifest == manifest
