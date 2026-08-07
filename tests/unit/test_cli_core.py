import json
import sys
from dataclasses import fields

import pytest

from goldilocks_core.advice import advise_parameters
from goldilocks_core.cli import core as cli_core
from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    KPointSelection,
    Provenance,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.examples import structure as example_structure

_VDW_METHODS = ("d3", "d3bj", "ts", "mbd")


def make_result(request: CoreJobRequest) -> CoreResult:
    """Build a minimal Core result for CLI tests."""
    analysis = StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
    )
    advice = advise_parameters(analysis, intent=request.intent, hints=request.hints)
    return CoreResult(
        intent=request.intent,
        analysis=analysis,
        advice=advice,
        k_points=KPointSelection(
            grid=(2, 2, 1),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="user_hint", reason="test"),
        ),
        selection=SelectionRecord(pseudopotentials=()),
    )


def test_build_parser_parses_recommend_arguments() -> None:
    """Parse staged recommendation arguments into a namespace."""
    parser = cli_core.build_parser()

    args = parser.parse_args(
        [
            "recommend",
            "Si.cif",
            "--functional",
            "PBEsol",
            "--k-grid",
            "2",
            "2",
            "1",
            "--model",
            "model.joblib",
            "--spin-polarized",
            "true",
            "--json",
        ]
    )

    assert args.command == "recommend"
    assert args.structure == "Si.cif"
    assert args.functional == "PBEsol"
    assert args.k_grid == [2, 2, 1]
    assert args.model == "model.joblib"
    assert args.spin_polarized == "true"
    assert args.json is True


def test_cli_public_control_parity_is_explicit_and_complete() -> None:
    """Map every public intent/hint field or mark it deliberately unexposed."""
    intent_cli_mapping = {
        "code": "--code",
        "task": "--task",
        "functional": "--functional",
        "pseudo_mode": "--pseudo-mode",
    }
    hints_cli_mapping = {
        "k_spacing": "--k-spacing",
        "k_grid": "--k-grid",
        "smearing_type": "--smearing-type",
        "smearing_width_ry": "--smearing-width-ry",
        "spin_polarized": "--spin-polarized",
        "spin_orbit_coupling": "--spin-orbit-coupling",
        # The CLI sets intent.pseudo_mode directly instead of exposing a
        # second override for the same effective pseudopotential family.
        "pseudo_mode": None,
        "pseudo_type": "--pseudo-type",
        "relativistic_mode": "--relativistic-mode",
        "conv_thr": "--conv-thr",
        "mixing_beta": "--mixing-beta",
        "electron_maxstep": "--electron-maxstep",
        "use_vdw": "--use-vdw",
        "vdw_method": "--vdw-method",
    }

    assert set(intent_cli_mapping) == {
        field.name for field in fields(CalculationIntent)
    }
    assert set(hints_cli_mapping) == {field.name for field in fields(CalculationHints)}

    parser = cli_core.build_parser()
    subparsers = next(action for action in parser._actions if action.dest == "command")
    recommend_parser = subparsers.choices["recommend"]
    option_destinations = {
        option: action.dest
        for action in recommend_parser._actions
        for option in action.option_strings
    }
    for field_name, option in {**intent_cli_mapping, **hints_cli_mapping}.items():
        if option is not None:
            assert option_destinations[option] == field_name

    args = parser.parse_args(
        [
            "recommend",
            "Si.cif",
            "--code",
            "quantum_espresso",
            "--task",
            "scf_single_point",
            "--functional",
            "PBEsol",
            "--pseudo-mode",
            "precision",
            "--k-spacing",
            "0.25",
            "--k-grid",
            "2",
            "3",
            "4",
            "--smearing-type",
            "cold",
            "--smearing-width-ry",
            "0.02",
            "--spin-polarized",
            "true",
            "--spin-orbit-coupling",
            "false",
            "--pseudo-type",
            "NC",
            "--relativistic-mode",
            "full",
            "--conv-thr",
            "1e-8",
            "--mixing-beta",
            "0.2",
            "--electron-maxstep",
            "120",
            "--use-vdw",
            "true",
            "--vdw-method",
            "ts",
        ]
    )

    request = cli_core._request_from_args(args)

    assert request.intent == CalculationIntent(
        code="quantum_espresso",
        task="scf_single_point",
        functional="PBEsol",
        pseudo_mode="precision",
    )
    assert request.hints == CalculationHints(
        k_spacing=0.25,
        k_grid=(2, 3, 4),
        smearing_type="cold",
        smearing_width_ry=0.02,
        spin_polarized=True,
        spin_orbit_coupling=False,
        pseudo_type="NC",
        relativistic_mode="full",
        conv_thr=1e-8,
        mixing_beta=0.2,
        electron_maxstep=120,
        use_vdw=True,
        vdw_method="ts",
    )


def test_cli_request_canonicalizes_functional_intent() -> None:
    """Normalize the CLI functional label through the shared intent boundary."""
    args = cli_core.build_parser().parse_args(
        ["recommend", "Si.cif", "--functional", "PBE_SOL"]
    )

    request = cli_core._request_from_args(args)

    assert request.intent.functional == "PBEsol"


@pytest.mark.parametrize(
    ("option", "expected"),
    [(None, None), ("true", True), ("false", False)],
)
def test_cli_preserves_use_vdw_tri_state(
    option: str | None,
    expected: bool | None,
) -> None:
    """Distinguish omitted vdW policy from explicit on and explicit off."""
    argv = ["recommend", "Si.cif"]
    if option is not None:
        argv.extend(["--use-vdw", option])

    request = cli_core._request_from_args(cli_core.build_parser().parse_args(argv))

    assert request.hints.use_vdw is expected


@pytest.mark.parametrize("vdw_method", _VDW_METHODS)
@pytest.mark.parametrize(
    ("use_vdw", "expected"),
    [(None, None), ("true", True)],
    ids=["omitted", "enabled"],
)
def test_cli_preserves_vdw_method_with_omitted_or_enabled_vdw(
    vdw_method: str,
    use_vdw: str | None,
    expected: bool | None,
) -> None:
    """Map every supported vdW method for omitted and enabled policy."""
    argv = ["recommend", "Si.cif", "--vdw-method", vdw_method]
    if use_vdw is not None:
        argv.extend(["--use-vdw", use_vdw])

    request = cli_core._request_from_args(cli_core.build_parser().parse_args(argv))

    assert request.hints.use_vdw is expected
    assert request.hints.vdw_method == vdw_method


@pytest.mark.parametrize("vdw_method", _VDW_METHODS)
def test_cli_rejects_every_vdw_method_when_vdw_is_disabled(vdw_method: str) -> None:
    """Reject every explicit method paired with a disabled vdW hint."""
    args = cli_core.build_parser().parse_args(
        ["recommend", "Si.cif", "--use-vdw", "false", "--vdw-method", vdw_method]
    )

    with pytest.raises(ValueError, match="vdw_method must be None"):
        cli_core._request_from_args(args)


@pytest.mark.parametrize("vdw_method", _VDW_METHODS)
def test_main_rejects_disabled_vdw_method_before_job_execution(
    vdw_method: str,
    monkeypatch,
    capsys,
) -> None:
    """Reject contradictory vdW options before invoking the Core job runner."""

    def fail_if_run(*args, **kwargs) -> CoreResult:
        pytest.fail("run_core_job must not be called for invalid CLI options")

    monkeypatch.setattr(cli_core, "run_core_job", fail_if_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "recommend",
            "Si.cif",
            "--use-vdw",
            "false",
            "--vdw-method",
            vdw_method,
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert "vdw_method must be None" in capsys.readouterr().err


def test_cli_uses_default_kmesh_backend_without_an_override() -> None:
    """A bare CLI request leaves the k-index model spec unset."""
    args = cli_core.build_parser().parse_args(["recommend", "Si.cif"])

    assert cli_core._model_spec_from_args(args) is None


@pytest.mark.parametrize("option", ["--model-name", "--model-version"])
def test_main_rejects_model_metadata_without_model_before_job_execution(
    option: str,
    monkeypatch,
    capsys,
) -> None:
    """Fail on backend-only metadata before invoking the Core job runner."""

    def fail_if_run(*args, **kwargs) -> CoreResult:
        pytest.fail("run_core_job must not be called for invalid CLI options")

    monkeypatch.setattr(cli_core, "run_core_job", fail_if_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "recommend", "Si.cif", option, "metadata"],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert f"{option} requires --model" in capsys.readouterr().err


def test_cli_rejects_removed_accuracy_control(capsys) -> None:
    """Do not accept an accuracy control with no scientific semantics."""
    parser = cli_core.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["recommend", "Si.cif", "--accuracy-level", "high"])

    assert "unrecognized arguments: --accuracy-level high" in capsys.readouterr().err


def test_main_builds_request_and_prints_json(monkeypatch, capsys) -> None:
    """Keep CLI main as parse -> request -> run_core_job -> print."""
    captured: dict[str, CoreJobRequest] = {}

    def fake_run_core_job(request: CoreJobRequest) -> CoreResult:
        captured["request"] = request
        return make_result(request)

    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "recommend",
            "Si.cif",
            "--k-grid",
            "2",
            "2",
            "1",
            "--pseudo-type",
            "NC",
            "--json",
        ],
    )

    cli_core.main()

    request = captured["request"]
    assert isinstance(request, CoreJobRequest)
    assert request.structure == "Si.cif"
    assert request.mode == "recommend"
    assert request.hints.k_grid == (2, 2, 1)
    assert request.hints.pseudo_type == "NC"
    output = json.loads(capsys.readouterr().out)
    assert output["k_points"]["grid"] == [2, 2, 1]
    assert output["request"]["structure"] == "Si.cif"


def test_main_builds_request_with_model_backend(monkeypatch, capsys) -> None:
    """Resolve CLI --model into a k-index model spec on the request."""
    captured: dict[str, CoreJobRequest] = {}

    def fake_run_core_job(request: CoreJobRequest) -> CoreResult:
        captured["request"] = request
        return make_result(request)

    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "recommend",
            "Si.cif",
            "--model",
            "model.joblib",
            "--model-name",
            "fixture-model",
            "--json",
        ],
    )

    cli_core.main()

    request = captured["request"]
    assert isinstance(request, CoreJobRequest)
    assert request.kmesh_model is not None
    assert request.kmesh_model.location == "model.joblib"
    assert request.kmesh_model.name == "fixture-model"
    assert json.loads(capsys.readouterr().out)["request"]["structure"] == "Si.cif"


def test_main_builds_generate_request_with_output_dir(monkeypatch, capsys) -> None:
    """Pass generate output path through the shared Core job request."""
    captured: dict[str, CoreJobRequest] = {}

    def fake_run_core_job(request: CoreJobRequest) -> CoreResult:
        captured["request"] = request
        result = make_result(request)
        return CoreResult(
            intent=result.intent,
            analysis=result.analysis,
            advice=result.advice,
            k_points=result.k_points,
            selection=result.selection,
            bundle=BundleRecord(path=request.output_dir, manifest={}),
        )

    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "generate", "Si.cif", "--out", "run"],
    )

    cli_core.main()

    assert captured["request"].mode == "generate"
    assert captured["request"].output_dir == "run"
    assert "bundle: run" in capsys.readouterr().out


def test_cli_has_no_bundle_subcommand() -> None:
    """The removed bundle subcommand is rejected by the parser."""
    parser = cli_core.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["bundle", "Si.cif", "--out", "run"])


def test_cli_analyze_prints_analysis(monkeypatch, capsys) -> None:
    """The analyze subcommand prints the structure analysis."""
    si_path = str(example_structure("Si.cif"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "analyze", si_path],
    )

    cli_core.main()

    out = capsys.readouterr().out
    assert "formula: Si" in out


def test_cli_kmesh_prints_k_points(monkeypatch, capsys) -> None:
    """The kmesh subcommand prints the resolved k-point grid."""
    si_path = str(example_structure("Si.cif"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "kmesh",
            si_path,
            "--k-grid",
            "2",
            "3",
            "4",
        ],
    )

    cli_core.main()

    out = capsys.readouterr().out
    assert "k-grid: 2 3 4" in out


def test_cli_generate_with_out_writes_bundle(monkeypatch, capsys, tmp_path) -> None:
    """The generate --out subcommand writes a bundle directory."""
    from goldilocks_core.pseudo.pp_metadata import PseudoMetadata

    si_path = str(example_structure("Si.cif"))
    output_dir = tmp_path / "bundle"

    def fake_load_pseudo_metadata(root):
        return [
            PseudoMetadata(
                filepath="/pseudo/Si.UPF",
                filename="Si.UPF",
                header_format="attr",
                library="SSSP",
                element="Si",
                pseudo_type="NC",
                functional="PBEsol",
                relativistic="scalar",
                sssp_recommended_cutoff={"ecutwfc_ry": 35, "ecutrho_ry": 140},
            )
        ]

    monkeypatch.setattr(cli_core, "load_pseudo_metadata", fake_load_pseudo_metadata)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "generate",
            si_path,
            "--k-grid",
            "2",
            "2",
            "2",
            "--pseudo-root",
            "/pseudo",
            "--out",
            str(output_dir),
        ],
    )

    cli_core.main()

    assert output_dir.exists()
    assert (output_dir / "inputs" / "qe.in").exists()
    assert (output_dir / "manifest.json").exists()
    assert f"bundle: {output_dir}" in capsys.readouterr().out


def test_cli_has_serve_subcommand_group() -> None:
    """The serve subcommand group exposes http and mcp children."""
    parser = cli_core.build_parser()

    http_args = parser.parse_args(
        ["serve", "http", "--host", "0.0.0.0", "--port", "9000"]
    )
    assert http_args.command == "serve"
    assert http_args.serve_command == "http"
    assert http_args.host == "0.0.0.0"
    assert http_args.port == 9000

    mcp_args = parser.parse_args(["serve", "mcp"])
    assert mcp_args.serve_command == "mcp"


def test_cli_serve_http_imports_lazily(monkeypatch) -> None:
    """serve http dispatches to server.http.serve without importing at module load."""
    captured: dict[str, object] = {}

    def fake_serve_http(*, host: str = "127.0.0.1", port: int = 8000) -> None:
        captured["host"] = host
        captured["port"] = port

    import goldilocks_core.server.http as http_module

    monkeypatch.setattr(http_module, "serve", fake_serve_http)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "serve", "http", "--host", "0.0.0.0", "--port", "9001"],
    )

    cli_core.main()

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9001


def test_cli_serve_mcp_imports_lazily(monkeypatch) -> None:
    """serve mcp dispatches to server.mcp.serve without importing at module load."""
    called: list[bool] = []

    def fake_serve_mcp() -> None:
        called.append(True)

    import goldilocks_core.server.mcp as mcp_module

    monkeypatch.setattr(mcp_module, "serve", fake_serve_mcp)
    monkeypatch.setattr(sys, "argv", ["goldilocks-core", "serve", "mcp"])

    cli_core.main()

    assert called == [True]
