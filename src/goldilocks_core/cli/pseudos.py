"""The ``gl pp`` commands: what can be installed, what is, and installing it."""

from __future__ import annotations

import argparse
import os
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

_NUMBER = f"{'#':>3}  "
"""A table's position in the listing, which ``install`` also accepts."""

_BRIEF_HEADER = f"{_NUMBER}{'NAME':<{_NAME_WIDTH}}STATE"

_SOURCE_MAX = 60
"""Cap on the URL column. Nothing registered comes close; a future entry that
does gets elided rather than pushing every other column off the screen."""


def _detailed_header(source_width: int) -> str:
    """Build the wide header once the URL column's width is known.

    Functional, relativistic treatment and accuracy are not columns: every one
    of them is already in the name, which is why the names are shaped the way
    they are. Transfer size is not either -- ``gl pp install`` quotes it before
    fetching, which is when it matters.
    """
    return (
        f"{_NUMBER}{'NAME':<{_NAME_WIDTH}}{'SOURCE':<{source_width + 2}}"
        f"{'VERSION':<9}{'ELEMENTS':>9}{'Ln':>4}{'An':>4}  STATE"
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


def run(args: argparse.Namespace) -> int:
    """Dispatch a ``gl pp`` subcommand."""
    if args.pp_command == "available":
        return _available(verbose=args.verbose)
    if args.pp_command == "list":
        return _installed()
    return _install(args.tables, everything=args.all)


def _available(*, verbose: bool = False) -> int:
    """Print the catalogue: everything Core knows how to install.

    A name already encodes provider, functional, accuracy and relativistic
    treatment, so the default listing is names alone -- enough to pick one and
    pass it to ``gl pp install``. ``-v`` adds the facts a name cannot carry:
    where it is fetched from, which upstream version, and what it covers.
    """
    registry = load_tables()
    default = default_table(registry)
    linked = verbose and _hyperlinks_render()
    source_width = min(
        max(len(table.upstream_url) for table in registry.values()), _SOURCE_MAX
    )

    print(_detailed_header(source_width) if verbose else _BRIEF_HEADER)
    for number, table in enumerate(registry.values(), start=1):
        state = "installed" if installer.is_installed(table) else "uninstalled"
        if table is default:
            state = f"{state} (default)"

        if verbose:
            source = _linked_cell(
                _elide(table.upstream_url, source_width),
                table.upstream_url,
                source_width + 2,
                linked=linked,
            )
            row = (
                f"{number:>3}  {table.name:<{_NAME_WIDTH}}{source}"
                f"{table.version:<9}{len(table.elements):>9}"
                f"{len(table.lanthanides):>4}{len(table.actinides):>4}  {state}"
            )
        else:
            row = f"{number:>3}  {table.name:<{_NAME_WIDTH}}{state}"
        print(row)

    print(
        f"\n  the default is {default.name}; "
        f"`{installer.INSTALL_COMMAND}` with no argument installs it"
    )
    print(f"  install others by name or number: `{installer.INSTALL_COMMAND} NAME|N`")
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


def _resolve(token: str, registry: dict[str, PseudoTable]) -> str | None:
    """Return the table ``token`` selects, by name or by listing number."""
    if token in registry:
        return token

    if token.isdigit():
        names = list(registry)
        if 1 <= int(token) <= len(names):
            return names[int(token) - 1]

    return None


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
        chosen = [(token, _resolve(token, registry)) for token in tokens]
        unresolved = [token for token, name in chosen if name is None]
        if unresolved:
            print(
                f"error: no such table: {', '.join(unresolved)}\n"
                f"       names and numbers 1-{len(registry)} are listed by "
                f"`{installer.AVAILABLE_COMMAND}`",
                file=sys.stderr,
            )
            return 2

        wanted = [name for _token, name in chosen] or [default_table(registry).name]

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

    total = sum(table.transfer_bytes or 0 for table in outstanding)
    print(
        f"Installing {len(outstanding)} tables, {total / 1e6:.0f} MB in total, "
        "from the providers listed below.\n"
    )


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


def _hyperlinks_render() -> bool:
    """Whether to emit OSC 8 links for this run.

    Only to a terminal: piping or redirecting has to yield plain text, or
    `gl pp available -v > file` would collect escape sequences. ``NO_COLOR`` is
    honoured as an escape hatch for terminals that print the sequence rather
    than ignoring it, which is what a terminal without OSC 8 should do.
    """
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _elide(url: str, width: int) -> str:
    """Shorten ``url`` to ``width``, keeping the part that says where it points.

    Truncation from the right leaves the scheme and host intact, which is the
    part identifying the source; the trailing record or path is what gets
    replaced by the ellipsis. The full URL is still what the link opens.
    """
    if len(url) <= width:
        return url

    return url[: width - 3] + "..."


def _linked_cell(text: str, url: str, width: int, *, linked: bool) -> str:
    """Return a fixed-width cell whose text opens ``url`` when clicked.

    Underlined, because a link nobody knows is a link may as well be plain
    text. The underline is ordinary SGR, which every terminal renders, so the
    affordance survives even where OSC 8 does not -- and in that case the cell
    still holds a whole URL, which terminals detect and open by themselves.

    The padding sits outside both, so the underline and the clickable region
    cover the URL rather than trailing space, and the column width is computed
    from what is visible rather than from the escape sequences' length.
    """
    padding = " " * max(0, width - len(text))

    if not linked:
        return f"{text}{padding}"

    underlined = f"\033[4m{text}\033[24m"
    return f"\033]8;;{url}\033\\{underlined}\033]8;;\033\\{padding}"
