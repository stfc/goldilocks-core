"""Thin CLI wrapper for the staged Core job runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    ModelSpec,
)
from goldilocks_core.jobs import CoreRuntime, Pipeline
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata


def build_parser() -> argparse.ArgumentParser:
    """Build the staged Core CLI parser."""
    parser = argparse.ArgumentParser(
        prog="goldilocks-core",
        description="Run the staged Goldilocks Core pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("recommend", "generate", "bundle"):
        subparser = subparsers.add_parser(command)
        _add_common_arguments(subparser)
        if command == "bundle":
            subparser.add_argument(
                "--out",
                required=True,
                help="Output directory for the portable Core bundle.",
            )

    _add_serve_subparser(subparsers)

    return parser


def main() -> None:
    """Run the staged Core CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "serve":
        try:
            _run_serve(args)
        except ValueError as error:
            parser.error(str(error))
        except ImportError as error:
            raise SystemExit(str(error)) from error
        return

    try:
        _validate_backend_options(args)
        request = _request_from_args(args)
        pipeline = _pipeline_from_args(args)
    except ValueError as error:
        parser.error(str(error))

    with CoreRuntime(pipeline=pipeline) as runtime:
        result = runtime.run(request)

    if args.json:
        output = {"request": request.to_dict(), **result.to_dict()}
        print(json.dumps(output, indent=2, sort_keys=True))
        return

    _print_human_summary(result)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by staged Core commands."""
    parser.add_argument("structure", help="Path to the input structure file.")
    parser.add_argument(
        "--code",
        default="quantum_espresso",
        choices=["quantum_espresso"],
        help="Target DFT code.",
    )
    parser.add_argument(
        "--task",
        default="scf_single_point",
        choices=["scf_single_point"],
        help="Calculation task.",
    )
    parser.add_argument("--functional", default="PBE")
    parser.add_argument("--pseudo-mode", default="efficiency")
    parser.add_argument("--pseudo-type")
    parser.add_argument("--relativistic-mode")
    parser.add_argument("--pseudo-root", help="Directory containing UPF files.")
    kpoint_backend = parser.add_mutually_exclusive_group()
    kpoint_backend.add_argument(
        "--model",
        help="Local ML model path for Kmesh-stage k-point selection.",
    )
    kpoint_backend.add_argument(
        "--heuristic-kpoints",
        action="store_true",
        help="Use heuristic k-point advice instead of the built-in QRF model.",
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

    return CoreJobRequest(
        structure=args.structure,
        intent=intent,
        hints=hints,
        mode=args.command,
        pseudo_metadata=pseudo_metadata,
        output_dir=getattr(args, "out", None),
    )


def _pipeline_from_args(args: argparse.Namespace) -> Pipeline | None:
    """Build the pipeline for the requested k-point backend.

    An explicit ``--model`` selects a local CSLR k-index model.
    ``--heuristic-kpoints`` selects advice-based resolution. Otherwise no
    override is returned and ``run_core_job`` uses the shared QRF default.
    Explicit k-point hints bypass model loading inside every built-in backend.
    """
    if args.model is not None:
        spec = ModelSpec(
            name=args.model_name or "cli-kmesh-model",
            version=args.model_version or "unknown",
            model_type="random_forest",
            target="k_index",
            feature_set="cslr",
            source="local",
            location=args.model,
        )
        return Pipeline(kmesh=ml_kmesh_advisor(spec))

    if args.heuristic_kpoints:
        return Pipeline(kmesh=resolve_kpoints_from_advice)

    return None


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
    grid = result.selection.k_points.grid
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


def _add_serve_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add the HTTP server subcommand (requires the optional [http] extra)."""
    serve = subparsers.add_parser(
        "serve",
        help="Run the HTTP API server (requires the [http] extra).",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host. Defaults to loopback; use 0.0.0.0 to expose.",
    )
    serve.add_argument("--port", type=int, default=8000, help="Bind port.")
    serve.add_argument(
        "--pseudo-root", help="Directory of UPF files for default pseudo metadata."
    )
    serve.add_argument(
        "--structure-root",
        help="Allowlist root for server-side structure paths.",
    )
    serve.add_argument(
        "--bundle-root",
        help="Root for bundle output directories (default: goldilocks_output).",
    )
    kpoint_backend = serve.add_mutually_exclusive_group()
    kpoint_backend.add_argument(
        "--model",
        help="Local ML Kmesh model path. Replaces the default QRF backend.",
    )
    kpoint_backend.add_argument(
        "--heuristic-kpoints",
        action="store_true",
        help="Use heuristic k-point advice instead of the default QRF model.",
    )
    serve.add_argument(
        "--model-name",
        help="Model name recorded in Kmesh provenance; requires --model.",
    )
    serve.add_argument(
        "--model-version",
        help="Model version recorded in metadata; requires --model.",
    )


def _run_serve(args: argparse.Namespace) -> None:
    """Delegate to the HTTP transport server, guarding the optional extra."""
    from goldilocks_core.server.http import serve as serve_app

    serve_app(
        host=args.host,
        port=args.port,
        pseudo_root=args.pseudo_root,
        structure_root=args.structure_root,
        bundle_root=args.bundle_root,
        model=args.model,
        model_name=args.model_name,
        model_version=args.model_version,
        heuristic_kpoints=args.heuristic_kpoints,
    )


if __name__ == "__main__":
    main()
