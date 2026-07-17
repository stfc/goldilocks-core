import json
from pathlib import Path

import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    Pipeline,
    run_core_job,
)
from goldilocks_core.contracts import (
    GeneratedFile,
    KPointSelection,
    Provenance,
    StructureFeatureVector,
)
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

    assert result.selection.k_points.grid == (2, 2, 1)
    assert result.selection.pseudopotentials[0].filename == "Si.UPF"
    assert result.generated_files == ()
    assert result.bundle is None


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


def test_run_core_job_aggregates_advice_warnings() -> None:
    """Surface scientific caveats in job-level warnings."""
    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        )
    )

    warning = "Verify smearing manually for likely metallic systems."
    assert warning in result.warnings
    assert result.warnings.count(warning) == 1


def test_run_core_job_uses_shared_default_qrf_backend(monkeypatch, tmp_path) -> None:
    """The Python job runner uses the same configured default as the CLI."""

    class FakeQRF:
        q = [0.05, 0.5, 0.95]

        def predict(self, features):
            return [[0.2], [0.25], [0.3]]

    checkpoint = tmp_path / "checkpoint.ckpt"
    atom_table = tmp_path / "atom-init.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    monkeypatch.setenv("GOLDILOCKS_METALLICITY_CHECKPOINT", str(checkpoint))
    monkeypatch.setenv("GOLDILOCKS_METALLICITY_ATOM_INIT", str(atom_table))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", lambda spec: FakeQRF())
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model",
        lambda path: object(),
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )

    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        )
    )

    assert result.selection.k_points.provenance.source == "model"
    assert result.selection.k_points.provenance.confidence == 0.9


def test_run_core_job_uses_custom_kmesh_backend() -> None:
    """Replace one pipeline backend without changing the rest."""

    def custom_kmesh(structure, hints, kpoint_advice):
        return KPointSelection(
            grid=(9, 8, 7),
            shift=(0, 0, 0),
            mesh_type=kpoint_advice.mesh_type,
            provenance=Provenance(source="model", reason="test backend"),
        )

    pipeline = Pipeline(kmesh=custom_kmesh)

    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        pipeline=pipeline,
    )

    assert result.selection.k_points.grid == (9, 8, 7)
    assert result.selection.k_points.provenance.source == "model"


def test_custom_generate_backend_can_add_a_calculation_task() -> None:
    """Let callers add tasks without changing the shared pipeline contracts."""

    def custom_generate(structure, intent, advice, selection):
        assert intent.task == "magnetic_nscf"
        return (GeneratedFile(path="inputs/nscf.in", content="custom\n"),)

    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            intent=CalculationIntent(task="magnetic_nscf"),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="generate",
        ),
        pipeline=Pipeline(generate=custom_generate),
    )

    assert result.generated_files[0].path == "inputs/nscf.in"


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

    assert result.generated_files[0].path == "inputs/qe.in"
    assert "2  2  1  0  0  0" in result.generated_files[0].content


def test_run_core_job_bundle_writes_output_directory(tmp_path: Path) -> None:
    """Run the configured job graph through Bundle and write files."""
    output_dir = tmp_path / "bundle"
    result = run_core_job(
        CoreJobRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="bundle",
            output_dir=str(output_dir),
        )
    )

    assert result.bundle is not None
    assert result.bundle.path == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["selection"]["k_points"]["grid"] == [2, 2, 1]
    assert result.bundle.manifest == manifest
