"""``goldilocks models list|show``: what ml models are registered (v2
epic 8, #8; populated for real in v2 epic 11, #11). Lists every model
``ml/registry.toml`` declares, whether or not it is actually installed
-- ``goldilocks assets status``/a fact's own ``approaches`` in
``capabilities`` are where "is it actually usable right now" lives.
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.capabilities import capabilities
from goldilocks_core.cli._output import write_json


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("models", help="List installed ml models.")
    model_commands = parser.add_subparsers(dest="models_command", required=True)
    model_commands.add_parser("list", help="List every installed model.")
    show = model_commands.add_parser("show", help="Show one model's details.")
    show.add_argument(
        "target", help="The ml_target to show (see 'goldilocks settings')."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def run(args: argparse.Namespace, out: TextIO) -> None:
    models = capabilities()["models"]
    if args.models_command == "show":
        matches = [model for model in models if model.get("target") == args.target]
        if args.json:
            write_json(out, matches)
            return
        if not matches:
            print(f"no installed model for target {args.target!r}", file=out)
            return
        for model in matches:
            print(model, file=out)
        return

    if args.json:
        write_json(out, models)
        return
    if not models:
        print("no ml models installed (ml integration lands in a later epic)", file=out)
        return
    for model in models:
        print(model, file=out)
