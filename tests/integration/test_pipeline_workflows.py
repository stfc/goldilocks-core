from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pymatgen.core import Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    DirectoryOutput,
    InMemoryStructureSource,
    PathStructureSource,
    PresetSelection,
    compute,
)
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.selection import SelectionRecord


def test_generate_crosses_every_in_memory_stage_with_real_backends(
    sodium_chloride_structure: Structure,
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
    tmp_path: Path,
) -> None:
    pseudos = (
        pseudo_metadata_factory(
            "Na",
            ecutwfc_ry=35.0,
            ecutrho_ry=140.0,
            root=tmp_path,
            materialize=True,
        ),
        pseudo_metadata_factory(
            "Cl",
            ecutwfc_ry=45.0,
            ecutrho_ry=180.0,
            root=tmp_path,
            materialize=True,
        ),
    )

    result = compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=InMemoryStructureSource(sodium_chloride_structure),
                hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
                pseudo_metadata=pseudos,
            ),
            selection=PresetSelection("generate"),
        )
    )

    assert result.records[StructureAnalysisRecord].elements == ("Cl", "Na")
    assert result.records[KPointSelection].grid == (4, 4, 4)
    assert {
        pseudo.element for pseudo in result.records[SelectionRecord].pseudopotentials
    } == {"Na", "Cl"}

    qe_input = result.records[GeneratedFiles][0].content
    assert "  nat = 2" in qe_input
    assert "  ntyp = 2" in qe_input
    assert "  ecutwfc = 45" in qe_input
    assert "  ecutrho = 180" in qe_input
    assert "Na  " in qe_input and "Na.UPF" in qe_input
    assert "Cl  " in qe_input and "Cl.UPF" in qe_input
    assert "4  4  4  0  0  0" in qe_input


def test_structure_file_to_publication_preserves_inputs_and_provenance(
    tmp_path,
    sodium_chloride_structure: Structure,
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
) -> None:
    structure_path = tmp_path / "NaCl.cif"
    sodium_chloride_structure.to(filename=structure_path)
    destination = tmp_path / "published"
    pseudos = (
        pseudo_metadata_factory(
            "Na",
            ecutwfc_ry=35.0,
            ecutrho_ry=140.0,
            root=tmp_path,
            materialize=True,
        ),
        pseudo_metadata_factory(
            "Cl",
            ecutwfc_ry=45.0,
            ecutrho_ry=180.0,
            root=tmp_path,
            materialize=True,
        ),
    )
    result = compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=PathStructureSource(structure_path),
                hints=CalculationHints(k_grid=(3, 5, 7), pseudo_type="NC"),
                pseudo_metadata=pseudos,
            ),
            selection=PresetSelection("generate"),
        ),
        output=DirectoryOutput(destination),
    )

    generated_path = destination / "inputs" / "qe.in"
    manifest = json.loads((destination / "goldilocks.json").read_text())

    assert generated_path.read_bytes() == result.records[GeneratedFiles][
        0
    ].content.encode("utf-8")
    assert manifest["records"]["generated_files"][0] == {
        "path": "inputs/qe.in",
        "role": "input",
    }
    assert manifest["records"]["k_points"]["grid"] == [3, 5, 7]
    assert manifest["records"]["k_points"]["provenance"]["source"] == "user_hint"
    assert result.publication is not None
    assert result.publication.path == str(destination.resolve())
