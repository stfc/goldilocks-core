from pymatgen.core import Lattice, Structure

from goldilocks_core import CalculationHints, recommend
from goldilocks_core.pipeline import bundle_recommendation
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def test_recommend_runs_staged_core_pipeline() -> None:
    """Run Load → Analyse → Advise → Select through the public API."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    metadata = PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        library="SSSP",
        element="Si",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 30, "ecutrho_ry": 120},
    )

    result = recommend(
        structure,
        hints=CalculationHints(k_grid=(3, 3, 3)),
        pseudo_metadata=[metadata],
    )

    assert result.analysis.reduced_formula == "Si"
    assert result.advice.k_points.provenance.source == "user_hint"
    assert result.selection.k_points.grid == (3, 3, 3)
    assert result.grid == (3, 3, 3)
    assert result.selection.pseudopotentials[0].filename == "Si.UPF"


def test_bundle_recommendation_returns_manifest_dict() -> None:
    """Bundle structured records into a JSON-safe manifest."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=["I"],
        coords=[[0.0, 0.0, 0.0]],
    )

    manifest = bundle_recommendation(recommend(structure))

    assert manifest["analysis"]["heavy_elements"] == ["I"]
    assert manifest["advice"]["spin_orbit"]["consider"] is True
    assert manifest["selection"]["k_points"]["grid"] == [8, 8, 8]
    assert manifest["contains_heavy_elements"] is True
