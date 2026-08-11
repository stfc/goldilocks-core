"""Thin CLI wrapper for the staged Core job runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from goldilocks_core import contracts
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CoreResult,
    ModelSpec,
    PresetRequest,
    QueryRequest,
)
from goldilocks_core.examples import structures_path
from goldilocks_core.generation import available_codes, available_tasks
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.runtime import query_records, run_core_job

_OUTPUT_TYPE_NAMES = (
    "StructureAnalysisRecord",
    "ParameterAdvice",
    "KPointSelection",
    "SelectionRecord",
    "GeneratedFiles",
)
_OUTPUT_TYPES = {name: getattr(contracts, name) for name in _OUTPUT_TYPE_NAMES}


def build_parser() -> argparse.ArgumentParser:
    """Build the staged Core CLI parser."""
    parser = argparse.ArgumentParser(
        prog="goldilocks-core",
        description="Run the staged Goldilocks Core pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("recommend", "generate"):
        subparser = subparsers.add_parser(command)
        _add_common_arguments(subparser)
        if command == "generate":
            subparser.add_argument(
                "--out",
                help="Output directory for a portable Core bundle.",
            )

    compute = subparsers.add_parser("compute")
    _add_common_arguments(compute)
    compute.add_argument(
        "--outputs",
        required=True,
        help="Comma-separated record type names to compute.",
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

    return parser


def main() -> None:
    """Run the staged Core CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "examples":
        print(structures_path())
        return

    try:
        _validate_backend_options(args)
        request = _request_from_args(args)
    except ValueError as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    if args.command == "compute":
        records = query_records(request)
        print(json.dumps(records.to_dict(), indent=2, sort_keys=True))
        return

    result = run_core_job(request)

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


def _request_from_args(args: argparse.Namespace) -> PresetRequest | QueryRequest:
    """Build a Core request from parsed CLI arguments.

    Returns a :class:`QueryRequest` for the ``compute`` command and a
    :class:`PresetRequest` (``recommend``/``generate``) otherwise.
    """
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
    kmesh_model = _model_spec_from_args(args)

    if args.command == "compute":
        return QueryRequest(
            structure=args.structure,
            outputs=_parse_outputs(args.outputs),
            intent=intent,
            hints=hints,
            pseudo_metadata=pseudo_metadata,
            kmesh_model=kmesh_model,
        )
    return PresetRequest(
        structure=args.structure,
        intent=intent,
        hints=hints,
        mode=args.command,
        pseudo_metadata=pseudo_metadata,
        output_dir=getattr(args, "out", None),
        kmesh_model=kmesh_model,
    )


def _parse_outputs(value: str) -> tuple[type, ...]:
    """Resolve comma-separated contract record names to output types."""
    names = [name.strip() for name in value.split(",")]
    if not names or any(not name for name in names):
        raise ValueError("--outputs must contain comma-separated record type names")

    unknown = [name for name in names if name not in _OUTPUT_TYPES]
    if unknown:
        available = ", ".join(_OUTPUT_TYPE_NAMES)
        invalid = ", ".join(unknown)
        raise ValueError(
            f"Unknown output record type(s): {invalid}. Available: {available}"
        )
    return tuple(_OUTPUT_TYPES[name] for name in names)


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


if __name__ == "__main__":
    main()
