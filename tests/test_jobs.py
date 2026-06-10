import json
from dataclasses import replace
from pathlib import Path

from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    CoreJobRequest,
    default_pipeline,
    run_core_job,
)
from goldilocks_core.contracts import KPointSelection, Provenance
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
    """Run the configured job graph through Select for recommendation mode."""
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
        "kmesh",
        "select",
    ]
    assert result.recommendation.selection.k_points.grid == (2, 2, 1)
    assert result.recommendation.selection.pseudopotentials[0].filename == "Si.UPF"
    assert result.generated_files == ()
    assert result.bundle_path is None


def test_run_core_job_aggregates_kmesh_warnings() -> None:
    """Surface Kmesh-stage provenance warnings at the job level."""
    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(
                k_grid=(2, 2, 1),
                k_spacing=0.2,
                pseudo_type="NC",
            ),
            pseudo_metadata=(make_metadata(),),
        )
    )

    warning = "Both k_grid and k_spacing were provided; explicit grid wins."
    assert warning in result.warnings
    assert [stage.name for stage in result.stages] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
    ]
    assert result.stages[3].warnings == (warning,)


def test_run_core_job_uses_custom_kmesh_backend() -> None:
    """Replace one pipeline backend without changing the rest."""

    def custom_kmesh(structure, hints, kpoint_advice):
        return KPointSelection(
            grid=(9, 8, 7),
            shift=(0, 0, 0),
            mesh_type=kpoint_advice.mesh_type,
            provenance=Provenance(source="model", reason="test backend"),
        )

    pipeline = replace(default_pipeline(), kmesh=custom_kmesh)

    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        pipeline=pipeline,
    )

    assert result.recommendation.selection.k_points.grid == (9, 8, 7)
    assert result.recommendation.selection.k_points.provenance.source == "model"


def test_run_core_job_uses_custom_generate_backend() -> None:
    """Replace Generate without editing job orchestration."""

    def custom_generate(structure, intent, advice, selection):
        from goldilocks_core.contracts import GeneratedFile

        return (GeneratedFile(path="inputs/custom.in", content="custom\n"),)

    pipeline = replace(default_pipeline(), generate=custom_generate)

    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="generate",
        ),
        pipeline=pipeline,
    )

    assert result.generated_files[0].path == "inputs/custom.in"
    assert result.generated_files[0].content == "custom\n"


def test_run_core_job_generate_adds_generated_files() -> None:
    """Run the configured job graph through Generate for generated files."""
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
    """Run the configured job graph through Bundle and write files."""
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
