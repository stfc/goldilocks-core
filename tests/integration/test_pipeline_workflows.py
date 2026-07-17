from __future__ import annotations

import json
from collections.abc import Callable

from pymatgen.core import Structure

from goldilocks_core import CalculationHints, generate, write_bundle
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def test_generate_crosses_every_in_memory_stage_with_real_backends(
    sodium_chloride_structure: Structure,
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
) -> None:
    """Exercise Load through Generate with real, network-free stage backends."""
    pseudos = [
        pseudo_metadata_factory("Na", ecutwfc_ry=35.0, ecutrho_ry=140.0),
        pseudo_metadata_factory("Cl", ecutwfc_ry=45.0, ecutrho_ry=180.0),
    ]

    result = generate(
        sodium_chloride_structure,
        hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
        pseudo_metadata=pseudos,
    )

    assert result.analysis.elements == ("Cl", "Na")
    assert result.selection.k_points.grid == (4, 4, 4)
    assert {pseudo.element for pseudo in result.selection.pseudopotentials} == {
        "Na",
        "Cl",
    }

    qe_input = result.generated_files[0].content
    assert "  nat = 2" in qe_input
    assert "  ntyp = 2" in qe_input
    assert "  ecutwfc = 45" in qe_input
    assert "  ecutrho = 180" in qe_input
    assert "Na  " in qe_input and "Na.UPF" in qe_input
    assert "Cl  " in qe_input and "Cl.UPF" in qe_input
    assert "4  4  4  0  0  0" in qe_input


def test_structure_file_to_bundle_preserves_generated_files_and_provenance(
    tmp_path,
    sodium_chloride_structure: Structure,
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
) -> None:
    """Exercise file loading and complete bundle writing end to end."""
    structure_path = tmp_path / "NaCl.cif"
    sodium_chloride_structure.to(filename=structure_path)
    output_dir = tmp_path / "bundle"
    pseudos = [
        pseudo_metadata_factory("Na", ecutwfc_ry=35.0, ecutrho_ry=140.0),
        pseudo_metadata_factory("Cl", ecutwfc_ry=45.0, ecutrho_ry=180.0),
    ]

    result = write_bundle(
        structure_path,
        output_dir,
        hints=CalculationHints(k_grid=(3, 5, 7), pseudo_type="NC"),
        pseudo_metadata=pseudos,
    )

    assert result.bundle is not None

    generated_path = output_dir / "inputs" / "qe.in"
    generated_bytes = generated_path.read_bytes()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    file_record = manifest["generated_files"][0]

    assert generated_bytes == result.generated_files[0].content.encode("utf-8")
    assert file_record == {
        "path": "inputs/qe.in",
        "role": "input",
    }
    assert manifest == result.bundle.manifest
    assert manifest["selection"]["k_points"]["grid"] == [3, 5, 7]
    assert manifest["advice"]["k_points"]["provenance"]["source"] == "user_hint"
