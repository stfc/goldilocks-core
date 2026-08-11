"""The ``gl pp`` commands: what can be installed, what is, and installing it."""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from goldilocks_core.pseudo import install as installer
from goldilocks_core.pseudo import local as local_tables
from goldilocks_core.pseudo.table_registry import (
    PseudoTable,
    default_table,
    load_tables,
)

_NAME_WIDTH = 33
"""Wide enough for the longest registered name, with a separating space left."""

_NUMBER = f"{'#':>3}  "
"""A table's position in the listing, which ``install`` also accepts."""

_BRIEF_HEADER = f"{_NUMBER}{'NAME':<{_NAME_WIDTH}}STATE"

_DETAILED_HEADER = (
    f"{_NUMBER}{'NAME':<{_NAME_WIDTH}}{'VERSION':<9}{'ELEMENTS':>9}"
    f"{'Ln':>4}{'An':>4}{'ON DISK':>10}  STATE"
)
"""Functional, relativistic treatment and accuracy are not columns: all three
are already in the name, which is why the names are shaped the way they are.
Neither is the source URL -- ``gl pp install`` prints it before fetching.

``ON DISK``, not download size: the compressed archive is about a third of
what it unpacks to, and the number a user needs before installing is the one
that has to fit."""


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``pp`` command group."""
    pseudos = subparsers.add_parser(
        "pp", help="Pseudopotential tables: what exists, what is installed."
    )
    commands = pseudos.add_subparsers(dest="pp_command", required=True)

    available = commands.add_parser(
        "available", help="Show pseudopotential tables goldilocks-core can install."
    )
    available.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also show upstream version and element coverage.",
    )

    commands.add_parser("list", help="Show installed tables and where they are.")

    install = commands.add_parser("install", help="Install one or more tables.")
    install.add_argument(
        "tables",
        nargs="*",
        metavar="NAME|N",
        help="Table names, or their numbers from `gl pp available`. "
        "Defaults to the one Core uses unprompted.",
    )
    install.add_argument(
        "--all",
        action="store_true",
        help="Install every registered table. A flag rather than a table named "
        "'all', so it can never collide with a real name.",
    )

    delete = commands.add_parser("delete", help="Remove installed tables from disk.")
    delete.add_argument(
        "tables",
        nargs="+",
        metavar="NAME|N",
        help="Table names, or their numbers from `gl pp available`.",
    )

    _add_parser(commands)


def _add_parser(commands: argparse._SubParsersAction) -> None:
    """Register ``gl pp add``, for pseudopotentials Core cannot fetch.

    Every option here is a fact about the table as a whole. Nothing element-level
    is accepted, on purpose: which element a file holds, what type it is and what
    cutoff it wants are read out of the files by ``parse_upf``, and a directory
    those cannot be read from is refused rather than half-added. Retyping
    per-element data that is already in the files invites a transcription error
    no later check would catch.
    """
    add = commands.add_parser(
        "add",
        help="Add pseudopotentials of your own, which Core cannot fetch.",
        description=(
            "Copy a directory of UPF files in as a table, so it lists, is "
            "selected from, and deletes like an installed one. For a public "
            "library everyone would want, open an issue at "
            "https://github.com/stfc/goldilocks-core/issues instead: those "
            "belong in the registry Core ships."
        ),
    )
    add.add_argument("path", metavar="PATH", help="Directory holding the .upf files.")
    add.add_argument(
        "--name",
        help="What to call it. Defaults to the directory's name. The "
        "relativistic suffix is appended if absent, as every table name "
        "carries one.",
    )
    add.add_argument(
        "--functional",
        required=True,
        help="Exchange-correlation functional the table was generated for, "
        "e.g. PBEsol. Checked against the structure's, never inferred.",
    )
    add.add_argument(
        "--relativistic",
        required=True,
        choices=("SR", "FR", "NR"),
        help="Relativistic treatment of the table as a whole. Only FR can "
        "satisfy spin-orbit coupling.",
    )
    add.add_argument(
        "--accuracy",
        required=True,
        choices=("efficiency", "precision"),
        help="Which tier this table is, in the vocabulary the registry uses.",
    )
    add.add_argument("--version", default="local", help="Your version label.")
    add.add_argument(
        "--licence",
        default=local_tables.UNSTATED,
        help="Recorded and shown before use, never interpreted.",
    )
    add.add_argument(
        "--citation",
        default=local_tables.UNSTATED,
        help="What someone using this table should cite.",
    )


def run(args: argparse.Namespace) -> int:
    """Dispatch a ``gl pp`` subcommand."""
    if args.pp_command == "available":
        return _available(verbose=args.verbose)
    if args.pp_command == "list":
        return _installed()
    if args.pp_command == "add":
        return _add(args)
    if args.pp_command == "delete":
        return _delete(args.tables)
    return _install(args.tables, everything=args.all)


def _available(*, verbose: bool = False) -> int:
    """Print the catalogue: everything Core knows how to install.

    A name already encodes provider, functional, accuracy and relativistic
    treatment, so the default listing is names alone -- enough to pick one and
    pass it to ``gl pp install``. ``-v`` adds the two facts a name cannot
    carry: which upstream version, and what it covers.
    """
    registry = load_tables()
    default = default_table(registry)

    print(_DETAILED_HEADER if verbose else _BRIEF_HEADER)
    for number, table in enumerate(registry.values(), start=1):
        state = "installed" if installer.is_installed(table) else "uninstalled"
        if table is default:
            state = f"{state} (default)"

        if verbose:
            row = (
                f"{number:>3}  {table.name:<{_NAME_WIDTH}}{table.version:<9}"
                f"{len(table.elements):>9}{len(table.lanthanides):>4}"
                f"{len(table.actinides):>4}"
                f"{_megabytes(table.installed_bytes):>10}  {state}"
            )
        else:
            row = f"{number:>3}  {table.name:<{_NAME_WIDTH}}{state}"
        print(row)

    print(
        f"\n  the default is {default.name}; "
        f"`{installer.INSTALL_COMMAND}` with no argument installs it"
    )
    print(f"  install others by name or number: `{installer.INSTALL_COMMAND} NAME|N`")
    print(
        f"  add pseudopotentials you already have: `{installer.ADD_COMMAND} PATH ...`"
    )
    if not verbose:
        print(f"  version and element coverage with `{installer.AVAILABLE_COMMAND} -v`")
    return 0


def _add(args: argparse.Namespace) -> int:
    """Add a user-owned table by copying it under Core's pseudopotential root."""
    try:
        table = local_tables.add(
            Path(args.path),
            name=args.name or Path(args.path).name,
            functional=args.functional,
            relativistic=args.relativistic,
            accuracy=args.accuracy,
            version=args.version,
            licence=args.licence,
            citation=args.citation,
        )
    except local_tables.NotAddable as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    destination = installer.install_path(table)
    print(f"added {table.name}")
    print(f"  {len(table.elements)} pseudopotentials copied to {destination}")
    print(f"  registered in {local_tables.local_registry_path()}")
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
    print(f"  add another directory with `{installer.ADD_COMMAND} PATH ...`")
    return 0


def _resolve(token: str, registry: dict[str, PseudoTable]) -> str | None:
    """Return the table ``token`` selects, by name or by listing number."""
    if token in registry:
        return token

    if token.isdigit():
        names = list(registry)
        if 1 <= int(token) <= len(names):
            return names[int(token) - 1]

    return None


def _resolve_all(
    tokens: list[str], registry: dict[str, PseudoTable]
) -> list[str] | None:
    """Resolve every token, or report the ones that name nothing and return None.

    All-or-nothing: a command that half-ran because one argument was a typo
    leaves the user reconstructing which half.
    """
    resolved = [(token, _resolve(token, registry)) for token in tokens]
    unresolved = [token for token, name in resolved if name is None]

    if unresolved:
        print(
            f"error: no such table: {', '.join(unresolved)}\n"
            f"       names and numbers 1-{len(registry)} are listed by "
            f"`{installer.AVAILABLE_COMMAND}`",
            file=sys.stderr,
        )
        return None

    return [name for _token, name in resolved]


def _delete(tokens: list[str]) -> int:
    """Remove installed tables from disk.

    No confirmation prompt, for the same reason installing has none: the
    command is the decision. Nothing is deleted that ``gl pp install`` cannot
    put back, and every path removed is printed.
    """
    registry = load_tables()
    wanted = _resolve_all(tokens, registry)
    if wanted is None:
        return 2

    for name in wanted:
        table = registry[name]
        if not installer.is_installed(table):
            print(f"{table.name} is not installed")
            continue

        freed = _bytes_on_disk(installer.installed_paths(table))
        for path in installer.uninstall(table):
            print(f"removed {path}")
        print(f"  {table.name}, {freed / 1e6:.1f} MB freed\n")

    return 0


def _bytes_on_disk(paths: tuple[Path, ...]) -> int:
    """Total size of ``paths``, recursing into directories."""
    return sum(
        sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        if path.is_dir()
        else path.stat().st_size
        for path in paths
    )


def _install(tokens: list[str], *, everything: bool = False) -> int:
    """Install the named tables, the default, or everything registered."""
    registry = load_tables()

    if everything and tokens:
        print(
            "error: --all installs every table; do not also name one",
            file=sys.stderr,
        )
        return 2

    if everything:
        wanted = list(registry)
    else:
        resolved = _resolve_all(tokens, registry)
        if resolved is None:
            return 2

        wanted = resolved or [default_table(registry).name]

    if everything:
        _announce_total(registry, wanted)

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


def _announce_total(registry: dict[str, PseudoTable], wanted: list[str]) -> None:
    """Quote the whole bill before the first byte of a bulk install.

    Naming one table is a decision about a known quantity; ``--all`` is not,
    and the total is most of an hour on a slow connection. Every other install
    path says what it costs first, so this one has to as well.
    """
    outstanding = [
        registry[name] for name in wanted if not installer.is_installed(registry[name])
    ]
    if not outstanding:
        return

    fetched = sum(table.transfer_bytes or 0 for table in outstanding)
    on_disk = sum(table.installed_bytes or 0 for table in outstanding)
    print(
        f"Installing {len(outstanding)} tables: {fetched / 1e6:.0f} MB to fetch, "
        f"{on_disk / 1e6:.0f} MB on disk once unpacked.\n"
    )


def _announce(table: PseudoTable) -> None:
    """Say what is about to be fetched, under what terms, and what to cite."""
    print(
        f"{table.name}  {_megabytes(table.transfer_bytes)} to fetch, "
        f"{_megabytes(table.installed_bytes)} on disk  {table.licence}"
    )
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


def _megabytes(size: int | None) -> str:
    """Format a byte count as the user will see it quoted."""
    if not size:
        return "-"
    return f"{size / 1e6:.1f} MB"
