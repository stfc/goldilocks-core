"""``goldilocks settings``: list every ``--set``-able key, its default,
and where its value can come from (v2 epic 8, #8) -- design point (1)-b's
own illustrative table ("k_index integer human . ml(cgcnn-v2) . heuristic").

The keys are capabilities' ``settings[]`` plus its overridable ``facts[]``
(``is_metal``, ``is_magnetic``, ...), listed under ``[analysis]`` with the
values they accept (#139). A step setting names the steps it applies to,
the names ``steps.<step>.KEY`` takes (#154).
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.capabilities import capabilities
from goldilocks_core.cli._output import write_json


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "settings", help="List every --set-able key, its type, and its sources."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def run(args: argparse.Namespace, out: TextIO) -> None:
    caps = capabilities()
    facts = [fact for fact in caps["facts"] if fact["overridable"]]
    if args.json:
        write_json(out, {"settings": caps["settings"], "facts": facts})
        return
    rows = [(s["key"], s["group"], s.get("enum"), s) for s in caps["settings"]]
    rows += [(f["key"], "analysis", f["values"], f) for f in facts]
    for key, group, values, entry in sorted(rows, key=lambda row: row[0]):
        default = entry.get("default")
        default_text = "" if default is None else f" (default {default!r})"
        print(f"{key} [{group}] {entry['type']}{default_text}", file=out)
        if values:
            print(f"  values: {', '.join(values)}", file=out)
        print(f"  sources: {' . '.join(entry['approaches'])}", file=out)
        if entry.get("steps"):
            print(f"  steps: {', '.join(entry['steps'])}", file=out)
        if entry["description"]:
            print(f"  {entry['description']}", file=out)
