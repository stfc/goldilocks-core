"""``goldilocks run``: advise -> generate -> submission script -> bundle,
published if ``-o/--out`` is given, otherwise a memory-only preview
(v2 epic 8, #8). Each phase is ``--task``'s function in
``service.TASK_PHASES`` (#118).

Memory-only is the default, not an auto-picked output directory: P8's
"never a silent download" extends in spirit to "never a silent write" --
``goldilocks run si.cif`` (the design doc's own "99% of the time"
example, with no ``-o``) previews exactly what *would* be published
without touching disk, via ``bundle.bundle_files`` (a pure function).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, TextIO

from goldilocks_core.bundle import (
    ArchiveOutput,
    BundleInput,
    DirectoryOutput,
    bundle_files,
    publish,
)
from goldilocks_core.cli._common import (
    Request,
    add_fetch_missing_argument,
    add_run_arguments,
    finding_lines,
    records_to_json,
    resolve_request,
)
from goldilocks_core.cli._output import write_json
from goldilocks_core.service import TASK_PHASES
from goldilocks_core.steps import default_shared_context


def _print_blocked_and_exit(lines: list[str]) -> None:
    """``lines`` (``finding_lines``: each finding and its remedies' --set
    flags) on stderr, then exit 2."""
    for line in lines:
        print(line, file=sys.stderr)
    raise SystemExit(2)


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "run", help="Generate a runnable input; publish it if -o/--out is given."
    )
    add_run_arguments(parser)
    add_fetch_missing_argument(parser)
    parser.add_argument(
        "-o",
        "--out",
        help="Directory (or a .zip path) to publish the bundle to; omit for a "
        "memory-only preview.",
    )


def _bundle_input(
    request: Request, args: argparse.Namespace
) -> tuple[BundleInput, Any]:
    """``args.task``'s phases in order: advise, check (exiting 2 with the
    gate's findings when it refuses the request), generate, the submission
    script and the bundle, all on one ``SharedContext``. Returns the bundle
    input and the advice it was built from."""
    phases = TASK_PHASES[args.task]
    ctx = default_shared_context()
    advice = phases.advise(
        request.structure,
        code=args.code,
        hpc=request.hpc,
        overrides=request.overrides,
        fetch_missing=args.fetch_missing,
    )
    report = phases.check(advice)
    if not report.ok:
        _print_blocked_and_exit(finding_lines(report.blocking))
    steps = phases.generate(advice, report, ctx=ctx)
    script = phases.render_submission(advice, request.hpc, args.code, steps)
    bundle_input = phases.to_bundle_input(
        advice,
        steps,
        script,
        ctx,
        code=args.code,
        hpc=request.hpc,
        assignments=request.assignments,
        source=request.source,
    )
    return bundle_input, advice


def run(args: argparse.Namespace, out: TextIO) -> None:
    bundle_input, advice = _bundle_input(resolve_request(args), args)

    if args.out is not None:
        output = (
            ArchiveOutput(args.out)
            if args.out.endswith(".zip")
            else DirectoryOutput(args.out)
        )
        publication = publish(bundle_input, output)
        if args.json:
            write_json(out, publication)
            return
        print(f"published {publication['kind']} to {publication['path']}", file=out)
        for file_path in publication["files"]:
            print(f"  {file_path}", file=out)
        return

    files = bundle_files(bundle_input)
    if args.json:
        write_json(
            out,
            {
                "files": [file["path"] for file in files],
                "records": records_to_json(bundle_input.records),
                "warnings": advice.warnings(),
                "layout": advice.tiers().layout(),
            },
        )
        return
    print("memory-only preview (pass -o/--out to publish):", file=out)
    for file in files:
        print(f"  {file['path']} ({len(file['content'])} bytes)", file=out)
