from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    PresetRequest,
    run_core_job,
)
from goldilocks_core.contracts import PseudoCutoffs, PseudoMetadata


def _make_si_structure() -> Structure:
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def _make_si_metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        provider="sssp",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=30,
            ecutrho_ry=120,
        ),
        source_identifier="synthetic/Si.UPF",
    )


def test_recommend_runs_staged_core_pipeline() -> None:
    """Run Load → Analyze → Advise → Kmesh → Select through the public API."""
    result = run_core_job(
        PresetRequest(
            structure=_make_si_structure(),
            hints=CalculationHints(k_grid=(3, 3, 3)),
            pseudo_metadata=(_make_si_metadata(),),
        )
    )

    assert result.analysis.reduced_formula == "Si"
    assert result.k_points.grid == (3, 3, 3)
    assert result.selection.pseudopotentials[0].filename == "Si.UPF"


def test_generate_runs_pipeline_through_generated_files() -> None:
    """Generate input files through the public Python API."""
    result = run_core_job(
        PresetRequest(
            structure=_make_si_structure(),
            mode="generate",
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(_make_si_metadata(),),
        )
    )

    assert result.generated_files[0].path == "inputs/qe.in"
    assert "3  3  3  0  0  0" in result.generated_files[0].content


def test_run_core_job_generate_with_output_dir_writes_bundle(tmp_path) -> None:
    """Write a portable bundle through the shared Core job request."""
    output_dir = tmp_path / "bundle"
    result = run_core_job(
        PresetRequest(
            structure=_make_si_structure(),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(_make_si_metadata(),),
            mode="generate",
            output_dir=str(output_dir),
        )
    )

    assert result.bundle is not None
    assert result.bundle.path == str(output_dir)
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "inputs" / "qe.in").exists()


def test_core_result_serializes_to_manifest_style_dict() -> None:
    """CoreResult serializes into a JSON-safe manifest-style dictionary."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["I"],
        coords=[[0.0, 0.0, 0.0]],
    )

    result = run_core_job(
        PresetRequest(
            structure=structure,
            hints=CalculationHints(k_grid=(8, 8, 8)),
            pseudo_metadata=(),
        )
    )
    manifest = result.to_dict()

    assert manifest["analysis"]["heavy_elements"] == ["I"]
    assert manifest["advice"]["spin_orbit"]["consider"] is True
    assert manifest["k_points"]["grid"] == [8, 8, 8]
    assert "contains_heavy_elements" not in manifest
