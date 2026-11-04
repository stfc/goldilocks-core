"""``goldilocks explain``: analysis, advisors and ``run``'s check, without
generating anything (v2 epic 8, #8): the ``advise`` and ``check`` of
``--task``'s row of ``service.TASK_PHASES`` (#118). Prints every decision
with its source, then one ``notice:`` line per routing notice of the request
(#154), then the findings ``run`` would refuse to generate an input for
(#165), as ``run`` prints them: one ``blocked:`` line each, followed by a
``try:`` line per remedy (#151). A scientifically incomplete or blocked
request still prints and exits 0: every task's ``advise`` marks what it
cannot decide unavailable or blocked instead of raising. ``--json`` returns
each finding's document under ``blocking`` and adds each record's tier and
step as ``layout`` (#187), as HTTP and MCP ``explain`` do.
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.cli._common import (
    add_fetch_missing_argument,
    add_run_arguments,
    finding_lines,
    format_field_state,
    notice_lines,
    records_to_json,
    resolve_request,
)
from goldilocks_core.cli._output import write_json
from goldilocks_core.service import TASK_PHASES


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "explain",
        help=(
            "Run analysis+advisors without generating files; print every "
            "decision, its source, and the blocking reasons run would report."
        ),
    )
    add_run_arguments(parser)
    add_fetch_missing_argument(parser)


def run(args: argparse.Namespace, out: TextIO) -> None:
    request = resolve_request(args)
    phases = TASK_PHASES[args.task]
    advice = phases.advise(
        request.structure,
        code=args.code,
        hpc=request.hpc,
        overrides=request.overrides,
        fetch_missing=args.fetch_missing,
    )
    report = phases.check(advice)
    tiers = advice.tiers()
    records = tiers.records()
    warnings = advice.warnings()
    if args.json:
        write_json(
            out,
            {
                "records": records_to_json(records),
                "warnings": warnings,
                "blocking": [finding.to_document() for finding in report.blocking],
                "layout": tiers.layout(),
            },
        )
        return
    for name, state in sorted(records.items()):
        print(f"{name}: {format_field_state(state)}", file=out)
    for line in notice_lines(warnings):
        print(line, file=out)
    for line in finding_lines(report.blocking):
        print(line, file=out)
