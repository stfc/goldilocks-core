from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from goldilocks_core.cli import core as cli_core

if TYPE_CHECKING:
    pass


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_DOCS = REPO_ROOT / "docs" / "cli.md"


# --- subcommand parsing -----------------------------------------------------


def test_mcp_subcommand_parses_all_options() -> None:
    """The mcp subcommand exposes roots and backend options (stdio only in v1)."""
    parser = cli_core.build_parser()
    args = parser.parse_args(
        [
            "mcp",
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

    assert args.command == "mcp"
    assert args.pseudo_root == "/pseudos"
    assert args.structure_root == "/structures"
    assert args.bundle_root == "/bundles"
    assert args.model == "model.joblib"
    assert args.model_name == "fixture"
    assert args.model_version == "1.0"
    assert args.heuristic_kpoints is False


def test_mcp_subcommand_has_no_transport_host_port_options() -> None:
    """v1 exposes stdio only: no --transport/--host/--port options."""
    parser = cli_core.build_parser()
    args = parser.parse_args(["mcp"])
    # stdio is the only v1 transport; no transport/host/port args exist.
    assert not hasattr(args, "transport")
    assert not hasattr(args, "host")
    assert not hasattr(args, "port")
    assert args.model is None
    assert args.heuristic_kpoints is False


def test_mcp_rejects_model_and_heuristic_together() -> None:
    """--model and --heuristic-kpoints are mutually exclusive."""
    parser = cli_core.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mcp", "--model", "m.joblib", "--heuristic-kpoints"])


def test_mcp_subcommand_exposes_backend_composition_options() -> None:
    """The mcp subcommand mirrors the serve backend composition options."""
    parser = cli_core.build_parser()
    subparsers = next(action for action in parser._actions if action.dest == "command")
    mcp_parser = subparsers.choices["mcp"]
    option_destinations = {
        option: action.dest
        for action in mcp_parser._actions
        for option in action.option_strings
    }

    expected = {
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

    # v1 is stdio only: no transport/host/port options are exposed.
    for absent in ("--transport", "--host", "--port"):
        assert absent not in option_destinations


def test_mcp_help_does_not_advertise_transport_host_port() -> None:
    """The mcp subcommand help documents stdio only, never --transport/--host/--port."""
    parser = cli_core.build_parser()
    subparsers = next(action for action in parser._actions if action.dest == "command")
    mcp_parser = subparsers.choices["mcp"]

    # The per-subcommand usage/help omits the unsupported transport flags.
    help_text = mcp_parser.format_help()
    for absent in ("--transport", "--host", "--port"):
        assert absent not in help_text

    # The parent parser advertises the stdio-only v1 transport in the mcp line.
    parent_help = parser.format_help()
    assert "stdio" in parent_help.lower()


def test_cli_docs_mcp_section_is_stdio_only() -> None:
    """docs/cli.md documents the mcp command as stdio-only with no transport flags.

    Regression guard for the final MCP review finding: the v1 command deliberately
    supports stdio only, so the documented synopsis and flag table must not advertise
    ``--transport`` / ``--host`` / ``--port`` as supported options.
    """
    text = CLI_DOCS.read_text(encoding="utf-8")
    # Slice the mcp section: from its header to the next top-level section.
    start = text.index("### mcp")
    end = text.index("\n## ", start)
    section = text[start:end]

    # The synopsis line shows no transport/host/port flags.
    synopsis_lines = [
        line for line in section.splitlines() if line.startswith("goldilocks-core mcp")
    ]
    assert synopsis_lines, "mcp synopsis line must be present"
    for line in synopsis_lines:
        assert "--transport" not in line
        assert "--host" not in line
        assert "--port" not in line

    # The flag table rows that list supported flags must not include these.
    table_rows = [line for line in section.splitlines() if line.startswith("| `")]
    for row in table_rows:
        assert "`--transport`" not in row
        assert "`--host`" not in row
        assert "`--port`" not in row

    # The section states the stdio-only v1 scope.
    assert "stdio only" in section.lower()


def test_mcp_subcommand_carries_no_request_or_out_fields() -> None:
    """The mcp subcommand carries no request body or CLI-only fields."""
    parser = cli_core.build_parser()
    args = parser.parse_args(["mcp"])
    assert not hasattr(args, "json")
    assert not hasattr(args, "structure")
    assert not hasattr(args, "out")


# --- main() delegation ------------------------------------------------------


def test_main_rejects_backend_metadata_without_model_before_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Backend-only metadata fails before the server starts."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "mcp", "--model-name", "fixture"],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert "--model-name requires --model" in capsys.readouterr().err


def test_main_rejects_model_and_heuristic_before_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Contradictory backends fail at CLI validation, not inside the server."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["goldilocks-core", "mcp", "--model", "m.joblib", "--heuristic-kpoints"],
    )

    with pytest.raises(SystemExit) as error:
        cli_core.main()

    assert error.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_main_delegates_to_server_run_with_built_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mcp builds the server and runs it over stdio.

    ``serve()`` runs the public ``_serve_stdio`` entry; replacing it with a no-op
    async capture lets us assert ``main()`` built a low-level server without
    touching stdin/stdout.
    """
    import goldilocks_core.server.mcp as server_mcp

    captured: dict[str, object] = {}

    async def fake_serve_stdio(server: object) -> None:
        captured["server"] = server

    monkeypatch.setattr(server_mcp, "_serve_stdio", fake_serve_stdio)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "goldilocks-core",
            "mcp",
            "--heuristic-kpoints",
        ],
    )

    cli_core.main()

    assert captured["server"] is not None


def test_main_raises_clear_error_when_mcp_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mcp raises a clear install hint when the [mcp] extra is absent."""
    import goldilocks_core.server.mcp as server_mcp

    monkeypatch.setattr(server_mcp, "Server", None)
    monkeypatch.setattr(server_mcp, "Tool", None)
    monkeypatch.setattr(server_mcp, "CallToolResult", None)

    monkeypatch.setattr(sys, "argv", ["goldilocks-core", "mcp", "--heuristic-kpoints"])
    with pytest.raises(SystemExit) as error:
        cli_core.main()
    assert "[mcp]" in str(error.value)


# --- backend composition helpers -------------------------------------------


def test_build_runtime_uses_heuristic_kpoints_when_requested() -> None:
    """--heuristic-kpoints builds a Pipeline with advice-based k-point resolution."""
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import _build_runtime

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
    from goldilocks_core.server.mcp import _build_runtime

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
    from goldilocks_core.server.mcp import _build_runtime

    runtime = _build_runtime(
        model=None,
        model_name=None,
        model_version=None,
        heuristic_kpoints=False,
    )

    assert runtime._pipeline.kmesh is not resolve_kpoints_from_advice
    assert callable(runtime._pipeline.kmesh)


def test_serve_validation_raises_value_error_for_backend_only_metadata() -> None:
    """serve() rejects backend-only metadata with ValueError before running."""
    from goldilocks_core.server.mcp import _validate_backend_options

    with pytest.raises(ValueError, match=r"--model-name requires --model"):
        _validate_backend_options(
            model=None,
            model_name="fixture",
            model_version=None,
            heuristic_kpoints=False,
        )


# --- import boundary -------------------------------------------------------


def test_core_import_does_not_load_mcp_transport() -> None:
    """import goldilocks_core does not import the MCP/HTTP transports or the mcp SDK.

    Run in a fresh subprocess so earlier tests that imported
    ``goldilocks_core.server.mcp`` do not leave the submodule attribute set on
    the package in this process.
    """
    import os
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import goldilocks_core, sys; "
                "assert 'goldilocks_core.server' not in sys.modules; "
                "assert 'goldilocks_core.server.mcp' not in sys.modules; "
                "assert 'goldilocks_core.server.http' not in sys.modules; "
                "assert 'mcp' not in sys.modules; "
                "assert 'fastapi' not in sys.modules; "
                "assert 'server' not in goldilocks_core.__all__; "
                "assert 'mcp' not in goldilocks_core.__all__"
            ),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_serve_raises_clear_error_when_mcp_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serve() raises a clear install hint when the [mcp] extra is absent."""
    import goldilocks_core.server.mcp as server_mcp

    monkeypatch.setattr(server_mcp, "Server", None)
    monkeypatch.setattr(server_mcp, "Tool", None)
    monkeypatch.setattr(server_mcp, "CallToolResult", None)

    with pytest.raises(ImportError, match=r"\[mcp\]"):
        server_mcp.serve(heuristic_kpoints=True)
