"""Thin CLI wrapper for the staged Core job runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    ModelSpec,
)
from goldilocks_core.contracts.serial import to_jsonable
from goldilocks_core.examples import structures_path
from goldilocks_core.generation import available_codes, available_tasks
from goldilocks_core.jobs import run_core_job
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.runtime import CoreRuntime

_RAW_STAGE_COMMANDS = ("analyze", "kmesh", "advise", "select")
_COMPOSED_COMMANDS = ("recommend", "generate")


def build_parser() -> argparse.ArgumentParser:
    """Build the staged Core CLI parser."""
    parser = argparse.ArgumentParser(
        prog="goldilocks-core",
        description="Run the staged Goldilocks Core pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in (*_RAW_STAGE_COMMANDS, *_COMPOSED_COMMANDS):
        subparser = subparsers.add_parser(command)
        _add_common_arguments(subparser)
        if command == "generate":
            subparser.add_argument(
                "--out",
                default=None,
                help="Output directory for a portable Core bundle.",
            )

    examples = subparsers.add_parser(
        "examples",
        help="Inspect the example structures bundled with the package.",
    )
    example_commands = examples.add_subparsers(dest="examples_command", required=True)
    example_commands.add_parser(
        "path",
        help="Print the directory holding the bundled example structures.",
    )

    _add_serve_subparser(subparsers)

    return parser


def main() -> None:
    """Run the staged Core CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "examples":
        print(structures_path())
        return

    if args.command == "serve":
        _run_serve(args)
        return

    try:
        _validate_backend_options(args)
        request = _request_from_args(args)
    except ValueError as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    if args.command in _RAW_STAGE_COMMANDS:
        result = _run_raw_stage(args.command, request)
        _print_output(args, result)
        return

    result = run_core_job(request)
    _print_output(args, result)


def _add_serve_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``serve`` subcommand group with ``http`` and ``mcp`` children."""
    serve = subparsers.add_parser(
        "serve",
        help="Run an HTTP or MCP server exposing the Core pipeline.",
    )
    serve_sub = serve.add_subparsers(dest="serve_command", required=True)

    http_parser = serve_sub.add_parser(
        "http",
        help="Run the HTTP server (requires the [http] extra).",
    )
    http_parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    http_parser.add_argument("--port", type=int, default=8000, help="Bind port.")

    serve_sub.add_parser(
        "mcp",
        help="Run the MCP server over stdio (requires the [mcp] extra).",
    )


def _run_serve(args: argparse.Namespace) -> None:
    """Dispatch a ``serve`` subcommand, importing optional deps lazily."""
    if args.serve_command == "http":
        from goldilocks_core.server.http import serve as serve_http

        serve_http(host=args.host, port=args.port)
    elif args.serve_command == "mcp":
        from goldilocks_core.server.mcp import serve as serve_mcp

        serve_mcp()


def _run_raw_stage(command: str, request: CoreJobRequest) -> Any:
    """Dispatch a raw stage subcommand to its CoreRuntime entrypoint."""
    with CoreRuntime() as runtime:
        return getattr(runtime, command)(request)


def _print_output(args: argparse.Namespace, result: Any) -> None:
    """Print JSON or a human-readable summary for the command output."""
    if args.json:
        output = {"request": request_to_jsonable(args), **to_jsonable(result)}
        print(json.dumps(output, indent=2, sort_keys=True))
        return

    if isinstance(result, CoreResult):
        _print_human_summary(result)
    else:
        _print_raw_summary(result)


def request_to_jsonable(args: argparse.Namespace) -> Any:
    """Serialize the request for JSON output."""
    request = _request_from_args(args)
    return request.to_dict()


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by staged Core commands."""
    parser.add_argument("structure", help="Path to the input structure file.")
    parser.add_argument(
        "--code",
        default="quantum_espresso",
        choices=available_codes(),
        help="Target DFT code.",
    )
    parser.add_argument(
        "--task",
        default="scf_single_point",
        choices=available_tasks(),
        help="Calculation task.",
    )
    parser.add_argument(
        "--functional",
        default="PBEsol",
        help="Exchange-correlation functional.",
    )
    parser.add_argument("--pseudo-mode", default="efficiency")
    parser.add_argument("--pseudo-type")
    parser.add_argument("--relativistic-mode")
    parser.add_argument("--pseudo-root", help="Directory containing UPF files.")
    parser.add_argument(
        "--model",
        help="Local ML k-index model path for k-point selection.",
    )
    parser.add_argument(
        "--model-name",
        help="Model name recorded in k-point provenance when --model is used.",
    )
    parser.add_argument(
        "--model-version",
        help="Model version recorded in metadata when --model is used.",
    )
    parser.add_argument("--k-spacing", type=float)
    parser.add_argument(
        "--k-grid",
        nargs=3,
        type=int,
        metavar=("NK1", "NK2", "NK3"),
    )
    parser.add_argument(
        "--smearing-type",
        choices=["fixed", "gaussian", "mp", "cold"],
    )
    parser.add_argument("--smearing-width-ry", type=float)
    parser.add_argument(
        "--spin-polarized",
        choices=["true", "false"],
        help="Override spin-polarization advice.",
    )
    parser.add_argument(
        "--spin-orbit-coupling",
        choices=["true", "false"],
        help="Override spin-orbit coupling advice.",
    )
    parser.add_argument(
        "--use-vdw",
        choices=["true", "false"],
        help="Force vdW on/off; omit to let Core decide.",
    )
    parser.add_argument(
        "--vdw-method",
        help="Preferred vdW method: d3, d3bj, ts, or mbd.",
    )
    parser.add_argument("--conv-thr", type=float)
    parser.add_argument("--mixing-beta", type=float)
    parser.add_argument("--electron-maxstep", type=int)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output.",
    )


def _request_from_args(args: argparse.Namespace) -> CoreJobRequest:
    """Build a Core job request from parsed CLI arguments."""
    intent = CalculationIntent(
        code=args.code,
        task=args.task,
        functional=args.functional,
        pseudo_mode=args.pseudo_mode,
    )
    hints = CalculationHints(
        k_spacing=args.k_spacing,
        k_grid=tuple(args.k_grid) if args.k_grid else None,
        smearing_type=args.smearing_type,
        smearing_width_ry=args.smearing_width_ry,
        spin_polarized=_parse_optional_bool(args.spin_polarized),
        spin_orbit_coupling=_parse_optional_bool(args.spin_orbit_coupling),
        pseudo_type=args.pseudo_type,
        relativistic_mode=args.relativistic_mode,
        conv_thr=args.conv_thr,
        mixing_beta=args.mixing_beta,
        electron_maxstep=args.electron_maxstep,
        use_vdw=_parse_optional_bool(args.use_vdw),
        vdw_method=args.vdw_method,
    )
    pseudo_metadata = (
        tuple(load_pseudo_metadata(Path(args.pseudo_root))) if args.pseudo_root else ()
    )

    mode = args.command if args.command in _COMPOSED_COMMANDS else "recommend"

    return CoreJobRequest(
        structure=args.structure,
        intent=intent,
        hints=hints,
        mode=mode,
        pseudo_metadata=pseudo_metadata,
        output_dir=getattr(args, "out", None),
        kmesh_model=_model_spec_from_args(args),
    )


def _model_spec_from_args(args: argparse.Namespace) -> ModelSpec | None:
    """Build a local k-index model spec when ``--model`` is given.

    Returns ``None`` when no local model is requested, so ``run_core_job``
    uses the shared QRF k-distance default. Explicit k-point hints bypass
    model loading inside ``resolve_kpoints``.
    """
    if args.model is None:
        return None
    return ModelSpec(
        name=args.model_name or "cli-kmesh-model",
        version=args.model_version or "unknown",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location=args.model,
    )


def _validate_backend_options(args: argparse.Namespace) -> None:
    """Reject local-model metadata when no local model backend is selected."""
    backend_only_options = [
        option
        for option, value in (
            ("--model-name", args.model_name),
            ("--model-version", args.model_version),
        )
        if value is not None
    ]
    if args.model is None and backend_only_options:
        options = " and ".join(backend_only_options)
        verb = "requires" if len(backend_only_options) == 1 else "require"
        raise ValueError(f"{options} {verb} --model")


def _parse_optional_bool(value: str | None) -> bool | None:
    """Parse optional true/false CLI values."""
    if value is None:
        return None
    return value == "true"


def _print_human_summary(result: CoreResult) -> None:
    """Print a small human-readable summary from the Core result."""
    grid = result.k_points.grid
    print(f"formula: {result.analysis.reduced_formula}")
    print(f"code: {result.intent.code}")
    print(f"task: {result.intent.task}")
    print(f"k-grid: {grid[0]} {grid[1]} {grid[2]}")
    if result.generated_files:
        print("generated files:")
        for generated_file in result.generated_files:
            print(f"  {generated_file.path}")
    if result.bundle is not None:
        print(f"bundle: {result.bundle.path}")
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")


def _print_raw_summary(record: Any) -> None:
    """Print a small human-readable summary for a raw stage record."""
    name = type(record).__name__
    if hasattr(record, "reduced_formula"):
        print(f"formula: {record.reduced_formula}")
        if hasattr(record, "elements"):
            print(f"elements: {' '.join(record.elements)}")
        if hasattr(record, "electronic_character"):
            print(f"electronic character: {record.electronic_character}")
    elif hasattr(record, "grid"):
        print(f"k-grid: {record.grid[0]} {record.grid[1]} {record.grid[2]}")
        if hasattr(record, "provenance"):
            print(f"provenance: {record.provenance.source}")
    elif hasattr(record, "pseudopotentials"):
        for pseudo in record.pseudopotentials:
            print(f"pseudo: {pseudo.element} {pseudo.filename}")
        if getattr(record, "warnings", ()):
            print("warnings:")
            for warning in record.warnings:
                print(f"  - {warning}")
    else:
        print(name)


if __name__ == "__main__":
    main()
