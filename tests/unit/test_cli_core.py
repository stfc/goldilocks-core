import json
import sys
from dataclasses import fields
from types import SimpleNamespace

import pytest

from goldilocks_core.advice import advise_parameters
from goldilocks_core.assets import AssetNotInstalled, AssetReference
from goldilocks_core.cli import core as cli_core
from goldilocks_core.contracts import (
    BundleRecord,
    CalculationHints,
    CalculationIntent,
    CoreRecords,
    CoreResult,
    KPointSelection,
    ParameterAdvice,
    PresetRequest,
    Provenance,
    QueryRequest,
    SelectionRecord,
    StructureAnalysisRecord,
)

_VDW_METHODS = ("d3", "d3bj", "ts", "mbd")


def make_result(request: PresetRequest | QueryRequest, *, runtime=None) -> CoreResult:
    """Build a minimal Core result for CLI tests."""
    del runtime
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


def make_records(request: QueryRequest, *, runtime=None) -> CoreRecords:
    """Build the records selected by a CLI compute request."""
    del runtime
    result = make_result(request)
    available = {
        StructureAnalysisRecord: result.analysis,
        ParameterAdvice: result.advice,
    }
    return CoreRecords(
        {output_type: available[output_type] for output_type in request.outputs or ()}
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
        "pseudo_accuracy": "--pseudo-accuracy",
    }
    hints_cli_mapping = {
        "k_spacing": "--k-spacing",
        "k_grid": "--k-grid",
        "smearing_type": "--smearing-type",
        "smearing_width_ry": "--smearing-width-ry",
        "spin_polarized": "--spin-polarized",
        "spin_orbit_coupling": "--spin-orbit-coupling",
        # Accuracy is request intent; the CLI exposes no duplicate hint flag.
        "pseudo_accuracy": None,
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
            "--pseudo-accuracy",
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
        pseudo_accuracy="precision",
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
            "goldilocks",
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
        ["goldilocks", "recommend", "Si.cif", option, "metadata"],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert f"{option} requires --model" in capsys.readouterr().err


def test_cli_rejects_retired_pseudo_mode_control(capsys) -> None:
    """Expose the typed accuracy tier rather than an ambiguous mode string."""
    parser = cli_core.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["recommend", "Si.cif", "--pseudo-mode", "precision"])

    assert "unrecognized arguments: --pseudo-mode" in capsys.readouterr().err


def test_main_compute_prints_requested_analysis_and_advice(monkeypatch, capsys) -> None:
    """Resolve multiple output names and print their CoreRecords as JSON."""
    captured: dict[str, QueryRequest] = {}

    def fake_query_records(request: QueryRequest, *, runtime=None) -> CoreRecords:
        del runtime
        captured["request"] = request
        return make_records(request)

    monkeypatch.setattr(cli_core, "query_records", fake_query_records)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks",
            "compute",
            "Si.cif",
            "--outputs",
            "analysis,advice",
        ],
    )

    cli_core.main()

    assert captured["request"].outputs == (
        StructureAnalysisRecord,
        ParameterAdvice,
    )
    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"analysis", "advice"}
    assert output["analysis"]["reduced_formula"] == "Si"
    assert "smearing" in output["advice"]


def test_main_compute_prints_only_requested_analysis(monkeypatch, capsys) -> None:
    """Return only the single record named by a compute query."""
    monkeypatch.setattr(cli_core, "query_records", make_records)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks",
            "compute",
            "Si.cif",
            "--outputs",
            "analysis",
        ],
    )

    cli_core.main()

    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"analysis"}
    assert output["analysis"]["reduced_formula"] == "Si"


def test_main_compute_rejects_unknown_output_type(monkeypatch, capsys) -> None:
    """Report the invalid contract name before running a compute query."""

    def fail_if_run(*args, **kwargs) -> CoreRecords:
        pytest.fail("query_records must not be called for invalid output types")

    monkeypatch.setattr(cli_core, "query_records", fail_if_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks",
            "compute",
            "Si.cif",
            "--outputs",
            "UnknownRecord",
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "Unknown output record type id(s): UnknownRecord" in message
    assert "analysis" in message


def test_main_builds_request_and_prints_json(monkeypatch, capsys) -> None:
    """Keep CLI main as parse -> request -> run_core_job -> print."""
    captured: dict[str, PresetRequest] = {}

    def fake_run_core_job(request: PresetRequest, *, runtime=None) -> CoreResult:
        del runtime
        captured["request"] = request
        return make_result(request)

    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks",
            "recommend",
            "Si.cif",
            "--k-grid",
            "2",
            "2",
            "1",
            "--pseudo-type",
            "NC",
            "--pseudo-table",
            "sssp-pbe-precision-sr",
            "--json",
        ],
    )

    cli_core.main()

    request = captured["request"]
    assert isinstance(request, PresetRequest)
    assert request.structure == "Si.cif"
    assert request.mode == "recommend"
    assert request.hints.k_grid == (2, 2, 1)
    assert request.hints.pseudo_type == "NC"
    assert request.pseudo_table == "sssp-pbe-precision-sr"
    output = json.loads(capsys.readouterr().out)
    assert output["k_points"]["grid"] == [2, 2, 1]
    assert output["request"]["structure"] == "Si.cif"


def test_main_builds_request_with_model_backend(monkeypatch, capsys) -> None:
    """Resolve CLI --model into a k-index model spec on the request."""
    captured: dict[str, PresetRequest] = {}

    def fake_run_core_job(request: PresetRequest, *, runtime=None) -> CoreResult:
        del runtime
        captured["request"] = request
        return make_result(request)

    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks",
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
    assert isinstance(request, PresetRequest)
    assert request.kmesh_model is not None
    assert request.kmesh_model.location == "model.joblib"
    assert request.kmesh_model.name == "fixture-model"
    assert json.loads(capsys.readouterr().out)["request"]["structure"] == "Si.cif"


def test_main_builds_generate_request_with_output_dir(monkeypatch, capsys) -> None:
    """Pass generate output path through the shared Core job request."""
    captured: dict[str, PresetRequest] = {}

    def fake_run_core_job(request: PresetRequest, *, runtime=None) -> CoreResult:
        del runtime
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
        ["goldilocks", "generate", "Si.cif", "--out", "run"],
    )

    cli_core.main()

    assert captured["request"].mode == "generate"
    assert captured["request"].output_dir == "run"
    assert "bundle: run" in capsys.readouterr().out


def test_main_fetches_only_the_missing_asset_then_retries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Install the exact structured dependency, never the default profile."""
    installed: list[str] = []
    calls = 0

    def fake_run_core_job(request, *, runtime):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AssetNotInstalled(
                AssetReference("pseudodojo-pbesol-efficiency-sr", "0.4"),
                runtime.asset_store.root,
            )
        return make_result(request)

    def fake_install(name, *, store):
        del store
        installed.append(name)
        return ()

    monkeypatch.setattr(cli_core, "install_assets", fake_install)
    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "recommend", "Si.cif", "--fetch-missing"],
    )

    cli_core.main()

    assert installed == ["pseudodojo-pbesol-efficiency-sr"]
    assert calls == 2
    assert "formula: Si" in capsys.readouterr().out


def test_main_prints_asset_status_without_installing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    """Inspect the default profile without invoking acquisition."""
    root = tmp_path / "configured-assets"
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(root))
    monkeypatch.setattr(
        cli_core,
        "asset_statuses",
        lambda name, *, store: (("qrf-kpoints", "QRF95", "missing"),),
    )
    monkeypatch.setattr(
        cli_core,
        "install_assets",
        lambda name, *, store: pytest.fail("status must not install assets"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "assets", "status"],
    )

    cli_core.main()

    assert capsys.readouterr().out == (
        f"asset root: {root}\nqrf-kpoints@QRF95: missing\n"
    )


def test_main_installs_named_asset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Install exactly the asset selected by the operator."""
    names: list[str] = []

    def fake_install(name: str, *, store) -> tuple[SimpleNamespace, ...]:
        del store
        names.append(name)
        return (SimpleNamespace(id=name, version="1"),)

    monkeypatch.setattr(cli_core, "install_assets", fake_install)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "assets", "install", "qrf-kpoints"],
    )

    cli_core.main()

    assert names == ["qrf-kpoints"]
    output = capsys.readouterr().out
    assert "asset root: " in output
    assert "qrf-kpoints@1: installed" in output
