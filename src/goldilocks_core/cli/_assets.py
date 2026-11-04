"""``goldilocks assets install|status|verify``: unchanged from v1 in
substance (``assets/store.py``/``assets/runtime.py`` were ported
verbatim in v2 epic 3, #4) -- only moved into this package and no
longer wrapping every exception in a local try/except, since v2's
asset-store errors are already ``ExpectedFailure`` subclasses that
``cli.core``'s one top-level handler now catches uniformly (P6).
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.assets.runtime import (
    install as install_assets,
    statuses as asset_statuses,
    verify as verify_assets,
)
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.cli._output import write_json
from goldilocks_core.examples.structures import structures_path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    assets = subparsers.add_parser(
        "assets", help="Install and inspect immutable runtime assets."
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
        operation.add_argument("--json", action="store_true", help="Print JSON output.")

    examples = subparsers.add_parser(
        "examples", help="Inspect the example structures bundled with the package."
    )
    example_commands = examples.add_subparsers(dest="examples_command", required=True)
    path_command = example_commands.add_parser(
        "path", help="Print the directory holding the bundled example structures."
    )
    path_command.add_argument("--json", action="store_true", help="Print JSON output.")


def run(args: argparse.Namespace, out: TextIO) -> None:
    if args.command == "examples":
        path = str(structures_path())
        if args.json:
            write_json(out, {"path": path})
            return
        print(path, file=out)
        return

    store = AssetStore()
    if not args.json:
        # Printed before install/status/verify runs, not after: if a
        # requested asset id doesn't exist, the user still immediately
        # knows where to go looking (design doc: "先打印 asset root").
        print(f"asset root: {store.root}", file=out)

    if args.assets_command == "install":
        assets = [
            {"id": asset.id, "version": asset.version, "state": "installed"}
            for asset in install_assets(args.name, store=store)
        ]
    elif args.assets_command == "status":
        assets = [
            {"id": asset_id, "version": version, "state": state}
            for asset_id, version, state in asset_statuses(args.name, store=store)
        ]
    else:
        assets = [
            {"id": asset.id, "version": asset.version, "state": "verified"}
            for asset in verify_assets(args.name, store=store)
        ]

    if args.json:
        write_json(out, {"asset_root": str(store.root), "assets": assets})
        return
    for asset in assets:
        print(f"{asset['id']}@{asset['version']}: {asset['state']}", file=out)
