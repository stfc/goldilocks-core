import json
import sys

from goldilocks_core.advice import advise_parameters
from goldilocks_core.cli import core as cli_core
from goldilocks_core.contracts import (
    BundleRecord,
    CoreJobRequest,
    CoreResult,
    KPointSelection,
    Provenance,
    SelectionRecord,
    StageRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.jobs import Pipeline


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
    # CLI echoes the request itself alongside the CoreResult fields
    assert output["request"]["structure"] == "Si.cif"
    assert output["selection"]["k_points"]["grid"] == [2, 2, 1]


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
            stages=result.stages,
            bundle=BundleRecord(
                path=request.output_dir, manifest={"manifest_version": 1}
            ),
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
