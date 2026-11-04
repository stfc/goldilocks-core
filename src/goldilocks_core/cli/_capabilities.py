"""``goldilocks capabilities``: the full reflected payload (v2 epic 8,
#8's ``capabilities()``) as a third thin entry point alongside HTTP's
``GET /capabilities`` and MCP's ``capabilities`` tool -- #62's own gap:
nothing on the CLI previously reached ``codes``/``tasks``/
``pseudopotential_tables``/``hpc_profiles``/``warnings``, only
``settings``/``models``/``assets status`` each covered their own
narrower slice.
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.capabilities import capabilities
from goldilocks_core.cli._output import write_json


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "capabilities",
        help="Print the full capabilities payload: codes, tasks, facts, "
        "settings, pseudopotential tables, HPC profiles, models, and warnings.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def run(args: argparse.Namespace, out: TextIO) -> None:
    caps = capabilities()
    if args.json:
        write_json(out, caps)
        return

    print(f"core_version: {caps['core_version']}", file=out)
    print(f"vocabulary_version: {caps['vocabulary_version']}", file=out)
    for code in caps["codes"]:
        tasks = ", ".join(code["tasks"])
        print(f"code: {code['id']} ({code['name']}) tasks={tasks}", file=out)
    for task in caps["tasks"]:
        executables = ", ".join(task["executables"])
        print(
            f"task: {task['id']} ({task['name']}) "
            f"step_count={task['step_count']} executables={executables}",
            file=out,
        )
    print(
        f"facts: {len(caps['facts'])} (see 'goldilocks inspect'/'goldilocks explain')",
        file=out,
    )
    print(f"settings: {len(caps['settings'])} (see 'goldilocks settings')", file=out)
    for table in caps["pseudopotential_tables"]:
        default = " [default]" if table["default"] else ""
        print(
            f"pseudopotential_table: {table['id']} "
            f"({table['functional']}, {table['accuracy']}){default}",
            file=out,
        )
    for profile in caps["hpc_profiles"]:
        print(f"hpc_profile: {profile['id']} ({profile['scheduler']})", file=out)
    if caps["models"]:
        for model in caps["models"]:
            print(f"model: {model}", file=out)
    else:
        print(
            "models: none installed yet (ml integration lands in a later epic)",
            file=out,
        )
    print(f"warnings: {len(caps['warnings'])} known warning codes", file=out)
    print(f"sources: {', '.join(caps['sources'])}", file=out)
