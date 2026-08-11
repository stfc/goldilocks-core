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

_NAME_WIDTH = 33
"""Wide enough for the longest registered name, with a separating space left."""

_BRIEF_HEADER = f"{'NAME':<{_NAME_WIDTH}}STATE"

_DETAILED_HEADER = (
    f"{'NAME':<{_NAME_WIDTH}}{'SOURCE':<15}{'VERSION':<9}{'XC':<8}{'REL':<5}"
    f"{'ACCURACY':<12}{'ELEMENTS':>9}{'Ln':>4}{'An':>4}{'SIZE':>9}  STATE"
)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``pp`` command group."""
    pseudos = subparsers.add_parser(
        "pp", help="Pseudopotential tables: what exists, what is installed."
    )
    commands = pseudos.add_subparsers(dest="pp_command", required=True)

    available = commands.add_parser(
        "available", help="Show every table Core can install."
    )
    available.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also show source, version, functional, coverage and size.",
    )

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
        return _available(verbose=args.verbose)
    if args.pp_command == "list":
        return _installed()
    return _install(args.tables)


def _available(*, verbose: bool = False) -> int:
    """Print the catalogue: everything Core knows how to install.

    A name already encodes provider, functional, accuracy and relativistic
    treatment, so the default listing is names alone -- enough to pick one and
    pass it to ``gl pp install``. ``-v`` adds the facts a name cannot carry:
    where it is fetched from, which upstream version, and what it covers.
    """
    registry = load_tables()
    default = default_table(registry)

    print(_DETAILED_HEADER if verbose else _BRIEF_HEADER)
    for table in registry.values():
        state = "installed" if installer.is_installed(table) else "uninstalled"

        if verbose:
            row = (
                f"{table.name:<{_NAME_WIDTH}}{table.provider:<15}{table.version:<9}"
                f"{table.functional:<8}{table.relativistic:<5}{table.accuracy:<12}"
                f"{len(table.elements):>9}{len(table.lanthanides):>4}"
                f"{len(table.actinides):>4}{_megabytes(table):>9}  {state}"
            )
        else:
            row = f"{table.name:<{_NAME_WIDTH}}{state}"
        print(row)

    print(f"\n  `{installer.INSTALL_COMMAND}` with no name installs {default.name}")
    print(f"  install a specific one with `{installer.INSTALL_COMMAND} NAME`")
    if not verbose:
        print(f"  source, version and coverage with `{installer.AVAILABLE_COMMAND} -v`")
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
