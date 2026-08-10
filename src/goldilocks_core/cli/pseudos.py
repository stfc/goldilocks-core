"""The ``gl pp`` commands: what can be installed, what is, and installing it."""

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

_AVAILABLE_HEADER = (
    f"{'NAME':<32}{'XC':<8}{'REL':<5}{'ACCURACY':<12}"
    f"{'ELEMENTS':>9}{'Ln':>4}{'An':>4}{'SIZE':>9}  STATE"
)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``pp`` command group."""
    pseudos = subparsers.add_parser(
        "pp", help="Pseudopotential tables: what exists, what is installed."
    )
    commands = pseudos.add_subparsers(dest="pp_command", required=True)

    commands.add_parser("available", help="Show every table Core can install.")
    commands.add_parser("list", help="Show installed tables and where they are.")

    install = commands.add_parser("install", help="Install one or more tables.")
    install.add_argument(
        "tables",
        nargs="*",
        help="Table names. Defaults to the one Core uses unprompted.",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch a ``gl pp`` subcommand."""
    if args.pp_command == "available":
        return _available()
    if args.pp_command == "list":
        return _installed()
    return _install(args.tables)


def _available() -> int:
    """Print the catalogue: everything Core knows how to install."""
    registry = load_tables()
    default = default_table(registry)

    print(_AVAILABLE_HEADER)
    for table in registry.values():
        marker = " *" if table is default else ""
        state = "installed" if installer.is_installed(table) else "-"
        print(
            f"{table.name + marker:<32}{table.functional:<8}{table.relativistic:<5}"
            f"{table.accuracy:<12}{len(table.elements):>9}{len(table.lanthanides):>4}"
            f"{len(table.actinides):>4}{_megabytes(table):>9}  {state}"
        )

    print(f"\n  * installed by `{installer.INSTALL_COMMAND}` when no table is named")
    print(f"  install one with `{installer.INSTALL_COMMAND} NAME`")
    return 0


def _installed() -> int:
    """Print what is on disk, and where, so it can be pointed at."""
    registry = load_tables()
    installed = installer.installed_tables(registry)

    if not installed:
        print("No pseudopotential table is installed.\n")
        print(f"  see what exists:  {installer.AVAILABLE_COMMAND}")
        print(f"  install the default:  {installer.INSTALL_COMMAND}")
        return 0

    for table in installed:
        path = installer.install_path(table)
        count = len(list(path.glob("*.upf", case_sensitive=False)))
        print(f"{table.name}")
        print(f"  {count} pseudopotentials, {table.functional}, {table.accuracy}")
        print(f"  {path}")

    print(f"\n  pseudopotentials live under {installer.pseudo_root()}")
    print("  pass that to --pseudo-root to use a table Core did not install")
    return 0


def _install(names: list[str]) -> int:
    """Install the named tables, or the default when none are named."""
    registry = load_tables()
    wanted = names or [default_table(registry).name]

    unknown = [name for name in wanted if name not in registry]
    if unknown:
        print(
            f"error: no such table: {', '.join(unknown)}\n"
            f"       run `{installer.AVAILABLE_COMMAND}` to see the names",
            file=sys.stderr,
        )
        return 2

    for name in wanted:
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
        print(
            textwrap.fill(
                " ".join(table.note.split()),
                76,
                initial_indent="  note ",
                subsequent_indent="       ",
            )
        )


def _megabytes(table: PseudoTable) -> str:
    """Format the transfer size as the user will see it quoted."""
    if not table.transfer_bytes:
        return "-"
    return f"{table.transfer_bytes / 1e6:.1f} MB"
