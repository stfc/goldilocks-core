import sys

from pymatgen.core import Lattice, Structure

from goldilocks_core.cli import cli_kmesh
from goldilocks_core.cli.cli_kmesh import build_parser
from goldilocks_core.contracts import KPointSelection, Provenance


def test_build_parser_parses_required_arguments() -> None:
    """Parse the required CLI arguments for k-mesh recommendation."""
    parser = build_parser()
    args = parser.parse_args(["example.cif", "--model", "model.joblib"])

    assert args.structure == "example.cif"
    assert args.model == "model.joblib"


def test_main_loads_structure_and_prints_recommended_mesh(
    monkeypatch,
    capsys,
) -> None:
    """Run the CLI main path without shelling out or loading a real model."""
    structure = Structure(
        lattice=Lattice.cubic(3.5),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )
    calls: dict[str, object] = {}

    def fake_load_structure(path: str) -> Structure:
        calls["structure_path"] = path
        return structure

    def fake_advise_kpoints(
        loaded_structure: Structure,
        spec,
    ) -> KPointSelection:
        calls["loaded_structure"] = loaded_structure
        calls["model_location"] = spec.location
        return KPointSelection(
            mesh_type="monkhorst-pack",
            grid=(3, 3, 3),
            shift=(0, 0, 0),
            provenance=Provenance(
                source="model",
                reason="test model",
                data_source=spec.name,
            ),
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-kmesh", "Si.cif", "--model", "model.joblib"],
    )
    monkeypatch.setattr(cli_kmesh, "load_structure", fake_load_structure)
    monkeypatch.setattr(cli_kmesh, "advise_kpoints", fake_advise_kpoints)

    cli_kmesh.main()

    assert calls["structure_path"] == "Si.cif"
    assert calls["loaded_structure"] is structure
    assert calls["model_location"] == "model.joblib"
    assert capsys.readouterr().out == "recommended mesh: (3, 3, 3)\n"
