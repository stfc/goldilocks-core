from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    CoreJobRequest,
    CoreResult,
    Pipeline,
    generate,
    recommend,
    run_core_job,
    write_bundle,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def _structure() -> Structure:
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def _metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        library="SSSP",
        element="Si",
        pseudo_type="NC",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )


def test_recommend_runs_staged_core_pipeline() -> None:
    """Run Load → Analyze → Advise → Kmesh → Select through the public API."""
    result = recommend(
        _structure(),
        hints=CalculationHints(k_grid=(3, 3, 3)),
        pseudo_metadata=[_metadata()],
    )

    assert isinstance(result, CoreResult)
    assert result.analysis.reduced_formula == "Si"
    assert result.advice.k_points.provenance.source == "user_hint"
    assert result.selection.k_points.grid == (3, 3, 3)
    assert result.selection.pseudopotentials[0].filename == "Si.UPF"
    assert result.bundle is None


def test_generate_runs_pipeline_through_generated_files() -> None:
    """Generate input files through the public Python API."""
    result = generate(
        _structure(),
        hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
        pseudo_metadata=[_metadata()],
    )

    assert isinstance(result, CoreResult)
    assert result.generated_files[0].path == "inputs/qe.in"
    assert "3  3  3  0  0  0" in result.generated_files[0].content


def test_write_bundle_runs_pipeline_and_writes_directory(tmp_path) -> None:
    """Write a portable bundle through the public Python API."""
    result = write_bundle(
        _structure(),
        str(tmp_path),
        hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
        pseudo_metadata=[_metadata()],
    )

    assert isinstance(result, CoreResult)
    assert result.bundle is not None
    assert result.bundle.path == str(tmp_path)
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "inputs" / "qe.in").exists()


def test_recommend_to_dict_returns_json_safe_dict() -> None:
    """Serialize a recommendation result via to_dict()."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["I"],
        coords=[[0.0, 0.0, 0.0]],
    )

    manifest = recommend(structure).to_dict()

    assert manifest["analysis"]["heavy_elements"] == ["I"]
    assert manifest["advice"]["spin_orbit"]["consider"] is True
    assert manifest["selection"]["k_points"]["grid"] == [8, 8, 8]
    assert "contains_heavy_elements" not in manifest
    assert "request" not in manifest


def test_pipeline_override_swaps_one_backend() -> None:
    """Pipeline(kmesh=...) swaps one stage while keeping defaults."""
    from goldilocks_core.contracts import KPointSelection, Provenance

    def fixed_kmesh(structure, hints, kpoint_advice):
        return KPointSelection(
            grid=(5, 5, 5),
            shift=(0, 0, 0),
            mesh_type=kpoint_advice.mesh_type,
            provenance=Provenance(source="default", reason="fixed test grid"),
        )

    result = run_core_job(
        CoreJobRequest(structure=_structure()),
        pipeline=Pipeline(kmesh=fixed_kmesh),
    )

    assert result.selection.k_points.grid == (5, 5, 5)
