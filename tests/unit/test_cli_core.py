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
    ComputationResult,
    ComputeRequest,
    KPointSelection,
    ParameterAdvice,
    PresetSelection,
    Provenance,
    Records,
    RecordSelection,
    SelectionRecord,
    StructureAnalysisRecord,
)

_VDW_METHODS = ("d3", "d3bj", "ts", "mbd")


def make_result(request: ComputeRequest, *, runtime=None) -> ComputationResult:
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
    advice = advise_parameters(
        analysis,
        intent=request.draft.intent,
        hints=request.draft.hints,
    )
    available = {
        StructureAnalysisRecord: analysis,
        ParameterAdvice: advice,
        KPointSelection: KPointSelection(
            grid=(2, 2, 1),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="user_hint", reason="test"),
        ),
        SelectionRecord: SelectionRecord(pseudopotentials=()),
    }
    selected = (
        request.selection.records
        if isinstance(request.selection, RecordSelection)
        else tuple(available)
    )
    return ComputationResult(
        draft=request.draft,
        task=request.draft.intent.task,
        task_revision="1",
        selection=request.selection,
        records=Records({record: available[record] for record in selected}),
    )


def test_build_parser_parses_recommend_arguments() -> None:
    args = cli_core.build_parser().parse_args(
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
    assert args.k_grid == [2, 2, 1]
    assert args.json is True


def test_cli_public_control_parity_is_explicit_and_complete() -> None:
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


def test_cli_builds_one_compute_request_for_a_preset() -> None:
    args = cli_core.build_parser().parse_args(
        [
            "recommend",
            "Si.cif",
            "--k-grid",
            "2",
            "3",
            "4",
            "--pseudo-table",
            "sssp-pbe-precision-sr",
        ]
    )

    request = cli_core._request_from_args(args)

    assert request.selection == PresetSelection("recommend")
    assert request.draft.hints.k_grid == (2, 3, 4)
    assert request.draft.pseudo_table == "sssp-pbe-precision-sr"


def test_cli_builds_one_compute_request_for_selected_records() -> None:
    args = cli_core.build_parser().parse_args(
        ["compute", "Si.cif", "--outputs", "analysis,advice"]
    )

    request = cli_core._request_from_args(args)

    assert request.selection == RecordSelection(
        (StructureAnalysisRecord, ParameterAdvice)
    )


@pytest.mark.parametrize(
    ("option", "expected"),
    [(None, None), ("true", True), ("false", False)],
)
def test_cli_preserves_use_vdw_tri_state(
    option: str | None,
    expected: bool | None,
) -> None:
    argv = ["recommend", "Si.cif"]
    if option is not None:
        argv.extend(["--use-vdw", option])

    request = cli_core._request_from_args(cli_core.build_parser().parse_args(argv))

    assert request.draft.hints.use_vdw is expected


@pytest.mark.parametrize("vdw_method", _VDW_METHODS)
def test_cli_rejects_every_vdw_method_when_vdw_is_disabled(vdw_method: str) -> None:
    args = cli_core.build_parser().parse_args(
        ["recommend", "Si.cif", "--use-vdw", "false", "--vdw-method", vdw_method]
    )

    with pytest.raises(ValueError, match="vdw_method must be None"):
        cli_core._request_from_args(args)


def test_main_rejects_invalid_options_before_computation(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli_core,
        "compute",
        lambda *args, **kwargs: pytest.fail("compute must not run"),
    )
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
            "ts",
        ],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert "vdw_method must be None" in capsys.readouterr().err


def test_main_compute_prints_only_selected_records(monkeypatch, capsys) -> None:
    captured: dict[str, ComputeRequest] = {}

    def fake_compute(request: ComputeRequest, *, runtime=None):
        captured["request"] = request
        return make_result(request, runtime=runtime)

    monkeypatch.setattr(cli_core, "compute", fake_compute)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "compute", "Si.cif", "--outputs", "analysis,advice"],
    )

    cli_core.main()

    assert isinstance(captured["request"].selection, RecordSelection)
    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"analysis", "advice"}


def test_main_preserves_preset_json_until_cli_migration(monkeypatch, capsys) -> None:
    captured: dict[str, ComputeRequest] = {}

    def fake_compute(request: ComputeRequest, *, runtime=None):
        captured["request"] = request
        return make_result(request, runtime=runtime)

    monkeypatch.setattr(cli_core, "compute", fake_compute)
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "recommend", "Si.cif", "--k-grid", "2", "2", "1", "--json"],
    )

    cli_core.main()

    assert captured["request"].selection == PresetSelection("recommend")
    output = json.loads(capsys.readouterr().out)
    assert output["k_points"]["grid"] == [2, 2, 1]
    assert "records" not in output
    assert output["request"]["structure"] == "Si.cif"
    assert output["request"]["mode"] == "recommend"


def test_main_generate_publishes_requested_bundle(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_core, "compute", make_result)
    monkeypatch.setattr(
        cli_core,
        "write_bundle_directory",
        lambda result, path: BundleRecord(path=path, manifest={}),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "generate", "Si.cif", "--out", "run"],
    )

    cli_core.main()

    assert "bundle: run" in capsys.readouterr().out


def test_main_fetches_only_the_missing_asset_then_retries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    installed: list[str] = []
    calls = 0

    def fake_compute(request, *, runtime):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AssetNotInstalled(
                AssetReference(
                    "pseudopotentials/pseudodojo-pbesol-efficiency-sr", "0.4"
                ),
                runtime.asset_store.root,
            )
        return make_result(request)

    monkeypatch.setattr(cli_core, "compute", fake_compute)
    monkeypatch.setattr(
        cli_core,
        "install_assets",
        lambda name, *, store: installed.append(name) or (),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks", "recommend", "Si.cif", "--fetch-missing"],
    )

    cli_core.main()

    assert installed == ["pseudopotentials/pseudodojo-pbesol-efficiency-sr"]
    assert calls == 2
    assert "formula: Si" in capsys.readouterr().out


def test_main_prints_asset_status_without_installing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    root = tmp_path / "configured-assets"
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(root))
    monkeypatch.setattr(
        cli_core,
        "asset_statuses",
        lambda name, *, store: (("qrf-kpoints", "QRF95", "missing"),),
    )
    monkeypatch.setattr(sys, "argv", ["goldilocks", "assets", "status"])

    cli_core.main()

    assert capsys.readouterr().out == (
        f"asset root: {root}\nqrf-kpoints@QRF95: missing\n"
    )


def test_main_installs_named_asset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    assert "qrf-kpoints@1: installed" in capsys.readouterr().out
