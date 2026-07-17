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
    StageRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.jobs import Pipeline
from goldilocks_core.kmesh import resolve_kpoints_from_advice

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
        selection=SelectionRecord(
            k_points=KPointSelection(
                grid=(2, 2, 1),
                shift=(0, 0, 0),
                mesh_type="monkhorst-pack",
                provenance=Provenance(source="user_hint", reason="test"),
            ),
            pseudopotentials=(),
        ),
        stages=(StageRecord(name="load"), StageRecord(name="select")),
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


def test_cli_uses_shared_default_pipeline_without_an_override() -> None:
    """A bare CLI request delegates default policy to run_core_job."""
    args = cli_core.build_parser().parse_args(["recommend", "Si.cif"])

    assert cli_core._pipeline_from_args(args) is None


def test_cli_can_select_explicit_heuristic_backend() -> None:
    """Expose a no-model backend choice without changing request data."""
    args = cli_core.build_parser().parse_args(
        ["recommend", "Si.cif", "--heuristic-kpoints"]
    )

    pipeline = cli_core._pipeline_from_args(args)

    assert isinstance(pipeline, Pipeline)
    assert pipeline.kmesh is resolve_kpoints_from_advice


def test_cli_rejects_model_and_heuristic_backend_together() -> None:
    """Reject contradictory backend configuration during argument parsing."""
    parser = cli_core.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "recommend",
                "Si.cif",
                "--model",
                "model.joblib",
                "--heuristic-kpoints",
            ]
        )


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
    captured: dict[str, CoreJobRequest | Pipeline | None] = {}

    def fake_run_core_job(
        request: CoreJobRequest,
        *,
        pipeline: Pipeline | None = None,
    ) -> CoreResult:
        captured["request"] = request
        captured["pipeline"] = pipeline
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
    assert captured["pipeline"] is None
    output = json.loads(capsys.readouterr().out)
    assert output["selection"]["k_points"]["grid"] == [2, 2, 1]
    assert output["request"]["structure"] == "Si.cif"


def test_main_builds_pipeline_for_model_backend(monkeypatch, capsys) -> None:
    """Resolve CLI --model into a custom Core pipeline, not request data."""
    captured: dict[str, CoreJobRequest | Pipeline | None] = {}

    def fake_run_core_job(
        request: CoreJobRequest,
        *,
        pipeline: Pipeline | None = None,
    ) -> CoreResult:
        captured["request"] = request
        captured["pipeline"] = pipeline
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
    pipeline = captured["pipeline"]
    assert isinstance(request, CoreJobRequest)
    assert isinstance(pipeline, Pipeline)
    assert request.to_dict().get("model") is None
    assert pipeline.kmesh is not Pipeline().kmesh
    assert json.loads(capsys.readouterr().out)["request"]["structure"] == "Si.cif"


def test_main_builds_bundle_request_with_output_dir(monkeypatch, capsys) -> None:
    """Pass bundle output path through the shared Core job request."""
    captured: dict[str, CoreJobRequest] = {}

    def fake_run_core_job(
        request: CoreJobRequest,
        *,
        pipeline: Pipeline | None = None,
    ) -> CoreResult:
        captured["request"] = request
        result = make_result(request)
        return CoreResult(
            intent=result.intent,
            analysis=result.analysis,
            advice=result.advice,
            selection=result.selection,
            bundle=BundleRecord(path=request.output_dir, manifest={}),
            stages=result.stages,
        )

    monkeypatch.setattr(cli_core, "run_core_job", fake_run_core_job)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "bundle", "Si.cif", "--out", "run"],
    )

    cli_core.main()

    assert captured["request"].mode == "bundle"
    assert captured["request"].output_dir == "run"
    assert "bundle: run" in capsys.readouterr().out
