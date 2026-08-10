"""The ``gl list pp`` and ``gl download pp`` commands."""

from __future__ import annotations

import argparse
import sys
import textwrap

from goldilocks_core.pseudo import install as installer
from goldilocks_core.pseudo.table_registry import (
    PseudoTable,
    default_table,
    load_tables,
)

_HEADER = (
    f"{'NAME':<32}{'XC':<8}{'REL':<5}{'ACCURACY':<12}"
    f"{'ELEMENTS':>9}{'Ln':>4}{'An':>4}{'SIZE':>9}  STATE"
)


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register ``list`` and ``download`` on the top-level parser."""
    listing = subparsers.add_parser("list", help="Show what Core can install.")
    listing.add_argument(
        "kind",
        nargs="?",
        default="pp",
        choices=("pp",),
        help="What to list. Only pseudopotential tables for now.",
    )

    download = subparsers.add_parser(
        "download", help="Install a pseudopotential table."
    )
    download.add_argument("kind", choices=("pp",), help="What to install.")
    download.add_argument(
        "tables",
        nargs="*",
        help="Table names. Defaults to the one table Core uses unprompted.",
    )


def run_list(args: argparse.Namespace) -> int:
    """Print every registered table and whether it is installed."""
    registry = load_tables()
    default = default_table(registry)

    print(_HEADER)
    for table in registry.values():
        marker = " *" if table is default else ""
        state = "installed" if installer.is_installed(table) else "-"
        print(
            f"{table.name + marker:<32}{table.functional:<8}{table.relativistic:<5}"
            f"{table.accuracy:<12}{len(table.elements):>9}{len(table.lanthanides):>4}"
            f"{len(table.actinides):>4}{_megabytes(table):>9}  {state}"
        )

    print(f"\n  * installed unprompted by `{installer.DOWNLOAD_COMMAND}`")
    print(f"  pseudopotentials live in {installer.pseudo_root()}")
    return 0


def run_download(args: argparse.Namespace) -> int:
    """Install the named tables, or the default when none are named."""
    registry = load_tables()
    names = args.tables or [default_table(registry).name]

    unknown = [name for name in names if name not in registry]
    if unknown:
        print(
            f"error: no such table: {', '.join(unknown)}\n"
            f"       run `{installer.LIST_COMMAND}` to see the names",
            file=sys.stderr,
        )
        return 2

    for name in names:
        table = registry[name]
        if installer.is_installed(table):
            print(
                f"{table.name} is already installed at {installer.install_path(table)}"
            )
            continue

        _announce(table)
        try:
            destination = installer.install(table)
        except installer.ProviderNotSupported as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

        count = len(list(destination.glob("*.upf", case_sensitive=False)))
        print(f"  {count} pseudopotentials verified against the published digests")
        print(f"  installed to {destination}\n")

    return 0


def _announce(table: PseudoTable) -> None:
    """Say what is about to be fetched, under what terms, and what to cite."""
    print(f"{table.name}  {_megabytes(table)}  {table.licence}")
    print(f"  from {table.upstream_url}")
    print(f"  cite {table.citation}")
    if table.note:
        wrapped = textwrap.fill(
            " ".join(table.note.split()),
            76,
            initial_indent="  note ",
            subsequent_indent="       ",
        )
        print(wrapped)


def _megabytes(table: PseudoTable) -> str:
    """Format the transfer size as the user will see it quoted."""
    if not table.transfer_bytes:
        return "-"
    return f"{table.transfer_bytes / 1e6:.1f} MB"
