from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from goldilocks_core.cli.core import main
from goldilocks_core.examples import structure


def _run_cli(
    *arguments: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "goldilocks_core.cli.core", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_capabilities_returns_canonical_json() -> None:
    completed = _run_cli("capabilities", "--json")

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["tasks"][0]["id"] == "scf_single_point"
    assert {preset["id"] for preset in document["tasks"][0]["presets"]} == {
        "recommend",
        "generate",
    }
    assert "quantum_espresso" in document["target_codes"]


def _pseudo_root(root: Path) -> Path:
    root.mkdir()
    pseudo = root / "Si.UPF"
    pseudo.write_text(
        '<UPF><PP_HEADER element="Si" pseudo_type="NC" '
        'functional="PBEsol" relativistic="scalar" z_valence="4.0" /></UPF>\n',
        encoding="utf-8",
    )
    (root / "cutoffs.json").write_text(
        json.dumps(
            {
                "Si": {
                    "filename": pseudo.name,
                    "md5": hashlib.md5(pseudo.read_bytes()).hexdigest(),
                    "functional": "PBEsol",
                    "cutoff_wfc": 30,
                    "cutoff_rho": 120,
                    "pseudopotential": "fixture/Si.UPF",
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "LICENSE.txt").write_text("Fixture licence\n", encoding="utf-8")
    (root / "goldilocks-pseudopotentials.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "licence": "Fixture-Licence",
                "licence_file": "LICENSE.txt",
                "citation": "Fixture pseudopotential citation.",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_cli_inspect_reports_structure_in_json_and_human_forms() -> None:
    sample_structure_path = str(structure("Si.cif"))
    structured = _run_cli("inspect", sample_structure_path, "--json")
    human = _run_cli("inspect", sample_structure_path)

    assert structured.returncode == 0, structured.stderr
    inspection = json.loads(structured.stdout)
    assert inspection["source"]["name"] == "Si.cif"
    assert inspection["structure"]["reduced_formula"] == "Si"
    assert human.returncode == 0, human.stderr
    assert "structure: Si.cif" in human.stdout
    assert "formula: Si" in human.stdout


def test_cli_inspect_rejects_an_invalid_structure_without_a_traceback(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.cif"
    broken.write_text("not a structure", encoding="utf-8")

    completed = _run_cli("inspect", str(broken), "--json")

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr


def test_cli_compute_preset_returns_canonical_memory_result(tmp_path: Path) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")
    completed = _run_cli(
        "compute",
        str(structure("Si.cif")),
        "--preset",
        "recommend",
        "--pseudo-root",
        str(pseudo_root),
        "--k-grid",
        "3",
        "3",
        "3",
        "--no-out",
        "--json",
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == 1
    assert result["selection"] == {"preset": "recommend"}
    assert result["draft"]["structure"]["structure"]["reduced_formula"] == "Si"
    assert result["records"]["k_points"]["grid"] == [3, 3, 3]
    assert result["publication"] is None


def _generate_arguments(pseudo_root: Path) -> tuple[str, ...]:
    return (
        "compute",
        str(structure("Si.cif")),
        "--preset",
        "generate",
        "--pseudo-root",
        str(pseudo_root),
        "--k-grid",
        "3",
        "3",
        "3",
        "--json",
    )


def test_cli_omitted_output_keeps_non_publishable_results_in_memory(
    tmp_path: Path,
) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")
    completed = _run_cli(
        "compute",
        str(structure("Si.cif")),
        "--preset",
        "recommend",
        "--pseudo-root",
        str(pseudo_root),
        "--k-grid",
        "3",
        "3",
        "3",
        "--json",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["publication"] is None
    assert not (tmp_path / "goldilocks_out").exists()


def test_cli_compute_publishes_an_explicit_directory(tmp_path: Path) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")
    destination = tmp_path / "ready"

    completed = _run_cli(*_generate_arguments(pseudo_root), "--out", str(destination))

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["publication"]["kind"] == "directory"
    assert result["publication"]["path"] == str(destination)
    assert (destination / "inputs" / "qe.in").is_file()
    assert (destination / "goldilocks.json").is_file()


@pytest.mark.parametrize("legal_material", ["complete", "absent", "blank"])
def test_cli_local_model_publication_requires_explicit_legal_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legal_material: str,
) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")
    destination = tmp_path / "ready"
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(tmp_path / "empty-assets"))
    monkeypatch.setattr(
        "goldilocks_core.advice.kindex.predict_kindex",
        lambda structure, spec: 1.0,
    )
    arguments = [
        "goldilocks",
        "compute",
        str(structure("Si.cif")),
        "--preset",
        "generate",
        "--pseudo-root",
        str(pseudo_root),
        "--model",
        str(tmp_path / "operator.joblib"),
        "--model-name",
        "operator-kmesh",
        "--model-version",
        "2026",
        "--out",
        str(destination),
        "--json",
    ]
    if legal_material != "absent":
        licence_file = tmp_path / "MODEL-LICENSE.txt"
        licence_file.write_text(
            "Operator redistribution terms.\n"
            if legal_material == "complete"
            else " \n",
            encoding="utf-8",
        )
        arguments.extend(
            [
                "--model-licence",
                "LicenseRef-Operator",
                "--model-licence-file",
                str(licence_file),
                "--model-citation",
                "Operator k-mesh model (2026).",
            ]
        )
    monkeypatch.setattr(sys, "argv", arguments)
    if legal_material != "complete":
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == 2
        assert not destination.exists()
        return

    main()
    result = json.loads(capsys.readouterr().out)
    assert result["publication"]["path"] == str(destination)
    manifest = json.loads((destination / "goldilocks.json").read_text())
    assert (
        manifest["records"]["k_points"]["provenance"]["data_source"] == "operator-kmesh"
    )
    assert [
        (model["name"], model["version"], model["licence"])
        for model in manifest["runtime"]["models"]
    ] == [("operator-kmesh", "2026", "LicenseRef-Operator")]
    assert (
        destination / "licences" / "custom-kmesh-model.txt"
    ).read_text() == "Operator redistribution terms.\n"
    assert "Operator k-mesh model (2026)." in (destination / "CITATIONS.md").read_text()


@pytest.mark.parametrize(
    "option", ["--model-licence", "--model-licence-file", "--model-citation"]
)
def test_cli_rejects_model_legal_options_without_a_model(
    option: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks",
            "compute",
            str(structure("Si.cif")),
            "--preset",
            "generate",
            option,
            "operator-metadata",
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--model" in capsys.readouterr().err


def test_cli_human_compute_summary_reports_science_and_publication(
    tmp_path: Path,
) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")
    destination = tmp_path / "ready"
    arguments = tuple(
        argument
        for argument in _generate_arguments(pseudo_root)
        if argument != "--json"
    )

    completed = _run_cli(*arguments, "--out", str(destination))

    assert completed.returncode == 0, completed.stderr
    assert "structure: Si.cif" in completed.stdout
    assert "formula: Si" in completed.stdout
    assert "code: quantum_espresso" in completed.stdout
    assert "task: scf_single_point" in completed.stdout
    assert "k-grid: 3 3 3" in completed.stdout
    assert "selection: Si=Si.UPF" in completed.stdout
    assert "dft input data:" in completed.stdout
    assert "pseudopotential set:" in completed.stdout
    assert f"published directory: {destination}" in completed.stdout


def test_cli_compute_publishes_an_explicit_archive(tmp_path: Path) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")
    destination = tmp_path / "ready.zip"

    completed = _run_cli(
        *_generate_arguments(pseudo_root), "--archive", str(destination)
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["publication"]["kind"] == "archive"
    assert result["publication"]["path"] == str(destination)
    assert destination.read_bytes().startswith(b"PK")


def test_cli_compute_automatically_publishes_complete_input_data(
    tmp_path: Path,
) -> None:
    pseudo_root = _pseudo_root(tmp_path / "pseudos")

    completed = _run_cli(*_generate_arguments(pseudo_root), cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["publication"]["kind"] == "directory"
    assert result["publication"]["path"] == str(tmp_path / "goldilocks_out")
    assert (tmp_path / "goldilocks_out" / "goldilocks.json").is_file()


def test_cli_human_advice_summary_uses_the_normalized_draft_formula() -> None:
    completed = _run_cli(
        "compute",
        str(structure("Si.cif")),
        "--outputs",
        "advice",
        "--smearing-type",
        "fixed",
        "--no-out",
    )

    assert completed.returncode == 0, completed.stderr
    assert "formula: Si" in completed.stdout
    assert "advice:" in completed.stdout
    assert "smearing=fixed" in completed.stdout
    assert "spin=off" in completed.stdout
    assert "SOC=off" in completed.stdout
    assert "pseudo=PBEsol/efficiency/any/scalar" in completed.stdout
    assert "vdW=off" in completed.stdout


def test_cli_compute_selected_records_uses_the_same_result_contract() -> None:
    completed = _run_cli(
        "compute",
        str(structure("Si.cif")),
        "--outputs",
        "analysis",
        "--no-out",
        "--json",
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["selection"] == {"records": ["analysis"]}
    assert set(result["records"]) == {"analysis"}
    assert result["records"]["analysis"]["reduced_formula"] == "Si"


def test_cli_exposes_no_recommend_or_generate_commands() -> None:
    help_text = _run_cli("--help")

    assert help_text.returncode == 0
    command_line = next(
        line for line in help_text.stdout.splitlines() if line.strip().startswith("{")
    )
    assert "recommend" not in command_line
    assert "generate" not in command_line


def test_cli_rejects_multiple_selection_and_output_variants() -> None:
    selection = _run_cli(
        "compute",
        "Si.cif",
        "--preset",
        "recommend",
        "--outputs",
        "analysis",
    )
    output = _run_cli(
        "compute",
        "Si.cif",
        "--outputs",
        "analysis",
        "--out",
        "run",
        "--archive",
        "run.zip",
    )

    assert selection.returncode == 2
    assert "not allowed with argument" in selection.stderr
    assert output.returncode == 2
    assert "not allowed with argument" in output.stderr
