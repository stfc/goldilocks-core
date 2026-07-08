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
from goldilocks_core.jobs import Pipeline, default_pipeline, run_core_job
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

    return parser


def main() -> None:
    """Run the staged Core CLI."""
    parser = build_parser()
    args = parser.parse_args()

    request = _request_from_args(args)
    result = run_core_job(request, pipeline=_pipeline_from_args(args))

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
    parser.add_argument(
        "--accuracy-level",
        default="standard",
        choices=["low", "standard", "high"],
    )
    parser.add_argument("--pseudo-mode", default="efficiency")
    parser.add_argument("--pseudo-type")
    parser.add_argument("--relativistic-mode")
    parser.add_argument("--pseudo-root", help="Directory containing UPF files.")
    parser.add_argument(
        "--model",
        help="Local ML model path for Kmesh-stage k-point selection.",
    )
    parser.add_argument(
        "--model-name",
        default="cli-kmesh-model",
        help="Model name recorded in k-point provenance when --model is used.",
    )
    parser.add_argument(
        "--model-version",
        default="unknown",
        help="Model version recorded in metadata when --model is used.",
    )
    parser.add_argument("--k-spacing", type=float)
    parser.add_argument(
        "--k-grid",
        nargs=3,
        type=int,
        metavar=("NK1", "NK2", "NK3"),
    )
    parser.add_argument("--smearing-type")
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
        accuracy_level=args.accuracy_level,
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

    Precedence: an explicit ``--model`` (local CSLR k-index model) wins; an
    explicit k-point hint (``--k-grid``/``--k-spacing``) resolves from advice
    without loading any model; otherwise the built-in default QRF pipeline runs
    (with heuristic fallback).
    """
    if args.model is not None:
        spec = ModelSpec(
            name=args.model_name,
            version=args.model_version,
            model_type="random_forest",
            target="k_index",
            feature_set="cslr",
            source="local",
            location=args.model,
        )
        return Pipeline(kmesh=ml_kmesh_advisor(spec))

    if args.k_grid is not None or args.k_spacing is not None:
        return None

    return default_pipeline()


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


if __name__ == "__main__":
    main()
