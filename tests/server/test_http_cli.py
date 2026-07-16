from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from goldilocks_core.cli import core as cli_core

if TYPE_CHECKING:
    pass


def test_serve_subcommand_parses_all_options() -> None:
    """The serve subcommand exposes host, port, roots, and backend options."""
    parser = cli_core.build_parser()
    args = parser.parse_args(
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--pseudo-root",
            "/pseudos",
            "--structure-root",
            "/structures",
            "--bundle-root",
            "/bundles",
            "--model",
            "model.joblib",
            "--model-name",
            "fixture",
            "--model-version",
            "1.0",
        ]
    )

    assert args.command == "serve"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.pseudo_root == "/pseudos"
    assert args.structure_root == "/structures"
    assert args.bundle_root == "/bundles"
    assert args.model == "model.joblib"
    assert args.model_name == "fixture"
    assert args.model_version == "1.0"
    assert args.heuristic_kpoints is False


def test_serve_defaults_to_loopback_host() -> None:
    """The default bind host is loopback, not a public interface."""
    args = cli_core.build_parser().parse_args(["serve"])
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.model is None
    assert args.heuristic_kpoints is False


def test_serve_rejects_model_and_heuristic_together() -> None:
    """--model and --heuristic-kpoints are mutually exclusive."""
    parser = cli_core.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["serve", "--model", "m.joblib", "--heuristic-kpoints"])


def test_main_rejects_backend_metadata_without_model_before_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend-only metadata fails before the server starts."""
    import uvicorn

    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail(
            "uvicorn.run must not be called for invalid options"
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "serve", "--model-name", "fixture"],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert "--model-name requires --model" in capsys.readouterr().err


def test_main_rejects_model_and_heuristic_before_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Contradictory backends fail at the CLI validation step, not inside uvicorn."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "serve", "--model", "m.joblib", "--heuristic-kpoints"],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_main_delegates_to_uvicorn_with_built_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serve builds the app and hands host/port to uvicorn.run without binding."""
    import uvicorn

    captured: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8042",
            "--heuristic-kpoints",
        ],
    )

    cli_core.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8042
    assert captured["app"] is not None


def test_build_runtime_uses_heuristic_kpoints_when_requested() -> None:
    """--heuristic-kpoints builds a Pipeline with advice-based k-point resolution."""
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import _build_runtime

    runtime = _build_runtime(
        model=None,
        model_name=None,
        model_version=None,
        heuristic_kpoints=True,
    )

    assert runtime._pipeline.kmesh is resolve_kpoints_from_advice


def test_build_runtime_uses_local_model_when_requested() -> None:
    """--model builds a Pipeline with a local CSLR k-point model backend."""
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import _build_runtime

    runtime = _build_runtime(
        model="model.joblib",
        model_name="fixture",
        model_version="1.0",
        heuristic_kpoints=False,
    )

    kmesh = runtime._pipeline.kmesh
    assert kmesh is not resolve_kpoints_from_advice
    assert callable(kmesh)


def test_build_runtime_default_uses_qrf_backend() -> None:
    """With no backend override, the runtime uses the default QRF Kmesh backend."""
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.http import _build_runtime

    runtime = _build_runtime(
        model=None,
        model_name=None,
        model_version=None,
        heuristic_kpoints=False,
    )

    assert runtime._pipeline.kmesh is not resolve_kpoints_from_advice
    assert callable(runtime._pipeline.kmesh)


def test_serve_raises_clear_error_when_http_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serve() raises a clear install hint when the [http] extra is absent."""
    import goldilocks_core.server.http as server_http

    monkeypatch.setattr(server_http, "FastAPI", None)
    monkeypatch.setattr(server_http, "Request", None)
    monkeypatch.setattr(server_http, "JSONResponse", None)
    monkeypatch.setattr(server_http, "HTTPException", None)

    with pytest.raises(ImportError, match=r"\[http\]"):
        server_http.serve(host="127.0.0.1", port=8000)


def test_serve_validation_raises_value_error_for_backend_only_metadata() -> None:
    """serve() rejects backend-only metadata with ValueError before uvicorn."""
    from goldilocks_core.server.http import _validate_backend_options

    with pytest.raises(ValueError, match=r"--model-name requires --model"):
        _validate_backend_options(
            model=None,
            model_name="fixture",
            model_version=None,
            heuristic_kpoints=False,
        )


def test_serve_subcommand_exposes_backend_composition_options() -> None:
    """The serve subcommand mirrors the recommend backend composition options."""
    parser = cli_core.build_parser()
    subparsers = next(action for action in parser._actions if action.dest == "command")
    serve_parser = subparsers.choices["serve"]
    option_destinations = {
        option: action.dest
        for action in serve_parser._actions
        for option in action.option_strings
    }

    expected = {
        "--host": "host",
        "--port": "port",
        "--pseudo-root": "pseudo_root",
        "--structure-root": "structure_root",
        "--bundle-root": "bundle_root",
        "--model": "model",
        "--heuristic-kpoints": "heuristic_kpoints",
        "--model-name": "model_name",
        "--model-version": "model_version",
    }
    for option, destination in expected.items():
        assert option_destinations[option] == destination, option


def test_serve_does_not_serialize_backend_in_request_json() -> None:
    """The serve subcommand carries no request body or backend request field."""
    parser = cli_core.build_parser()
    args = parser.parse_args(["serve"])
    assert not hasattr(args, "json")
    assert not hasattr(args, "structure")
    assert not hasattr(args, "out")
