from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.assets.runtime import (
    install as install_assets,
    statuses as asset_statuses,
    verify as verify_assets,
)
from goldilocks_core.assets.store import AssetCorrupt, AssetNotInstalled, AssetStore
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.examples.structures import structures_path
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.generation.registry import available_codes, available_tasks
from goldilocks_core.input_data import DftInputData
from goldilocks_core.io.structures import PathStructureSource, StructureInputError
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.publication import ArchiveOutput, DirectoryOutput, OutputTarget
from goldilocks_core.request import (
    CalculationDraft,
    ComputeRequest,
    PresetSelection,
    RecordSelection,
)
from goldilocks_core.result import ComputationResult
from goldilocks_core.runtime.jobs import compute
from goldilocks_core.runtime.models import Runtime
from goldilocks_core.runtime.registry import resolve_output_types
from goldilocks_core.runtime.service import Service
from goldilocks_core.selection import SelectionRecord
from goldilocks_core.serialization import to_portable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goldilocks",
        description="Run the staged Goldilocks Core pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities = subparsers.add_parser(
        "capabilities", help="Describe available Core tasks, presets, and assets."
    )
    capabilities.add_argument("--json", action="store_true", help="Print JSON output.")

    inspect = subparsers.add_parser("inspect", help="Inspect a structure source.")
    inspect.add_argument("structure", help="Path to the input structure file.")
    inspect.add_argument("--json", action="store_true", help="Print JSON output.")

    compute = subparsers.add_parser("compute", help="Run one Core computation.")
    _add_common_arguments(compute)
    selection = compute.add_mutually_exclusive_group(required=True)
    selection.add_argument("--preset", help="Named computation preset id.")
    selection.add_argument(
        "--outputs", help="Comma-separated record type ids to compute."
    )
    output = compute.add_mutually_exclusive_group()
    output.add_argument("--out", help="Publish a ready-to-run directory.")
    output.add_argument("--archive", help="Publish a ready-to-run ZIP archive.")
    output.add_argument(
        "--no-out", action="store_true", help="Return memory-only structured output."
    )

    serve = subparsers.add_parser(
        "serve",
        help="Run an optional HTTP or MCP transport.",
    )
    transports = serve.add_subparsers(dest="transport", required=True)
    http = transports.add_parser("http", help="Run the HTTP transport.")
    http.add_argument("--host", default="127.0.0.1")
    http.add_argument("--port", type=int, default=8000)
    http.add_argument(
        "--static-root",
        type=Path,
        help=(
            "Directory containing the built Workbench. "
            "Defaults to GOLDILOCKS_WORKBENCH_STATIC_ROOT."
        ),
    )
    transports.add_parser("mcp", help="Run the MCP stdio transport.")

    examples = subparsers.add_parser(
        "examples",
        help="Inspect the example structures bundled with the package.",
    )
    example_commands = examples.add_subparsers(dest="examples_command", required=True)
    example_commands.add_parser(
        "path",
        help="Print the directory holding the bundled example structures.",
    )

    assets = subparsers.add_parser(
        "assets",
        help="Install and inspect immutable runtime assets.",
    )
    asset_commands = assets.add_subparsers(dest="assets_command", required=True)
    for command in ("install", "status", "verify"):
        operation = asset_commands.add_parser(command)
        operation.add_argument(
            "name",
            nargs="?",
            default="default",
            help="Asset id or shipped profile name (default: default).",
        )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "capabilities":
        with Service() as service:
            capabilities = service.capabilities()
        if args.json:
            print(json.dumps(to_portable(capabilities), indent=2, sort_keys=True))
        else:
            print(f"Goldilocks Core {capabilities['core_version']}")
            for task in capabilities["tasks"]:
                presets = ", ".join(preset["id"] for preset in task["presets"])
                print(f"{task['id']}: {presets}")
        return
    if args.command == "inspect":
        try:
            with Service() as service:
                inspection = service.inspect_structure(
                    PathStructureSource(args.structure)
                )
        except (StructureInputError, ValueError) as error:
            parser.print_usage(sys.stderr)
            print(f"{parser.prog}: error: {error}", file=sys.stderr)
            raise SystemExit(2) from error
        if args.json:
            print(json.dumps(to_portable(inspection), indent=2, sort_keys=True))
        else:
            print(f"structure: {inspection.source.name}")
            print(f"formula: {inspection.structure.reduced_formula}")
            print(f"sites: {inspection.structure.site_count}")
        return
    if args.command == "examples":
        print(structures_path())
        return
    if args.command == "serve":
        _serve(args)
        return
    if args.command == "assets":
        _assets(args, parser)
        return

    store = AssetStore()
    attempted: set[tuple[str, str]] = set()
    try:
        _validate_backend_options(args)
        request = _request_from_args(args)
        target = _output_from_args(args)
        while True:
            try:
                with Runtime(asset_store=store) as runtime:
                    output = compute(request, runtime=runtime, output=target)
                break
            except AssetNotInstalled as error:
                key = (error.reference.id, error.reference.version)
                if not args.fetch_missing or key in attempted:
                    raise
                attempted.add(key)
                install_assets(error.reference.id, store=store)
    except (
        AssetCorrupt,
        AssetNotInstalled,
        FileExistsError,
        KeyError,
        ValueError,
    ) as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    if args.json:
        print(json.dumps(to_portable(output), indent=2, sort_keys=True))
        return

    _print_human_summary(output)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument(
        "--pseudo-accuracy",
        choices=["efficiency", "precision"],
        default="efficiency",
    )
    parser.add_argument("--pseudo-type")
    parser.add_argument("--relativistic-mode")
    parser.add_argument("--pseudo-root", help="Directory containing UPF files.")
    parser.add_argument(
        "--pseudo-table",
        help="Exact registered pseudopotential table id (default: registry default).",
    )
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Install only missing assets required by the request, then retry.",
    )
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


def _request_from_args(args: argparse.Namespace) -> ComputeRequest:
    intent = CalculationIntent(
        code=args.code,
        task=args.task,
        functional=args.functional,
        pseudo_accuracy=args.pseudo_accuracy,
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
    pseudo_root = str(Path(args.pseudo_root).expanduser()) if args.pseudo_root else None
    kmesh_model = _model_spec_from_args(args)

    selection = (
        PresetSelection(args.preset)
        if args.preset is not None
        else RecordSelection(_parse_outputs(args.outputs))
    )
    return ComputeRequest(
        draft=CalculationDraft(
            structure=PathStructureSource(args.structure),
            intent=intent,
            hints=hints,
            pseudo_root=pseudo_root,
            pseudo_table=args.pseudo_table,
            kmesh_model=kmesh_model,
        ),
        selection=selection,
    )


def _output_from_args(args: argparse.Namespace) -> OutputTarget | None:
    if args.no_out:
        return None
    if args.out is not None:
        return DirectoryOutput(args.out)
    if args.archive is not None:
        return ArchiveOutput(args.archive)
    return DirectoryOutput()


def _parse_outputs(value: str) -> tuple[type, ...]:
    names = [name.strip() for name in value.split(",")]
    if any(not name for name in names):
        raise ValueError("--outputs must contain comma-separated record type ids")
    return resolve_output_types(names)


def _assets(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    store = AssetStore()
    print(f"asset root: {store.root}")
    try:
        if args.assets_command == "install":
            installed = install_assets(args.name, store=store)
            for asset in installed:
                print(f"{asset.id}@{asset.version}: installed")
            return
        if args.assets_command == "status":
            for asset_id, version, state in asset_statuses(args.name, store=store):
                print(f"{asset_id}@{version}: {state}")
            return
        installed = verify_assets(args.name, store=store)
        for asset in installed:
            print(f"{asset.id}@{asset.version}: verified")
    except (AssetCorrupt, AssetNotInstalled, KeyError, ValueError) as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


def _serve(args: argparse.Namespace) -> None:
    if args.transport == "http":
        from goldilocks_core.server.http import serve

        serve(
            host=args.host,
            port=args.port,
            static_root=args.static_root,
        )
        return

    from goldilocks_core.server.mcp import serve

    serve()


def _model_spec_from_args(args: argparse.Namespace) -> ModelSpec | None:
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
    if value is None:
        return None
    return value == "true"


def _print_human_summary(result: ComputationResult) -> None:
    structure = result.draft.structure
    print(f"structure: {structure.source.name}")
    print(f"formula: {structure.structure.reduced_formula}")
    print(f"code: {result.draft.intent.code}")
    print(f"task: {result.draft.intent.task}")
    advice = result.records.get(ParameterAdvice)
    if advice is not None:
        smearing = advice.smearing.smearing_type or "none"
        if advice.smearing.width_ry is not None:
            smearing = f"{smearing}@{advice.smearing.width_ry:g} Ry"
        pseudo_type = advice.pseudopotential_requirements.pseudo_type or "any"
        soc = (
            "on"
            if advice.spin_orbit.enabled
            else "consider"
            if advice.spin_orbit.consider
            else "off"
        )
        print(
            "advice: "
            f"smearing={smearing}; "
            f"spin={'on' if advice.magnetism.spin_polarized else 'off'}; "
            f"SOC={soc}; "
            "pseudo="
            f"{advice.pseudopotential_requirements.functional}/"
            f"{advice.pseudopotential_requirements.accuracy}/"
            f"{pseudo_type}/"
            f"{advice.pseudopotential_requirements.relativistic}; "
            f"vdW={'on' if advice.vdw.use_vdw else 'off'}"
        )
    k_points = result.records.get(KPointSelection)
    if k_points is not None:
        grid = k_points.grid
        print(f"k-grid: {grid[0]} {grid[1]} {grid[2]}")
    selection = result.records.get(SelectionRecord)
    if selection is not None:
        selected = ", ".join(
            f"{pseudo.element}={pseudo.filename or 'unresolved'}"
            for pseudo in selection.pseudopotentials
        )
        print(f"selection: {selected or 'no pseudopotentials'}")
    input_data = result.records.get(DftInputData)
    if input_data is not None:
        print(
            f"dft input data: {len(input_data.artifacts)} artifacts, "
            f"{len(input_data.citations)} citations"
        )
        pseudo_set = input_data.pseudopotential_set
        version = f"@{pseudo_set.version}" if pseudo_set.version is not None else ""
        print(f"pseudopotential set: {pseudo_set.id}{version}")
    generated_files = result.records.get(GeneratedFiles, ())
    if generated_files:
        print("generated files:")
        for generated_file in generated_files:
            print(f"  {generated_file.path}")
    if result.publication is not None:
        print(f"published {result.publication.kind}: {result.publication.path}")
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
