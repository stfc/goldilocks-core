"""Install registered pseudopotential tables, and report what is installed.

Nothing here runs on its own. A table arrives because the user asked for it --
``gl download pp`` -- so there is no prompt to design and no unattended
download to guard against. What Core owes the user instead is a clear account
of what is missing and the command that fixes it.
"""

from __future__ import annotations

import json
from pathlib import Path

from goldilocks_core.artifacts import pseudodojo, sssp
from goldilocks_core.artifacts.cache import artifact_path
from goldilocks_core.artifacts.remote import HttpClient
from goldilocks_core.contracts import PathLike
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.pseudo.table_registry import (
    PseudoTable,
    default_table,
    load_tables,
)

INSTALL_COMMAND = "gl pp install"
"""What a user runs to install the default table."""

AVAILABLE_COMMAND = "gl pp available"
"""What a user runs to see every table Core can install."""

LIST_COMMAND = "gl pp list"
"""What a user runs to see the tables already on disk."""


class NoPseudopotentials(RuntimeError):
    """No pseudopotential table is installed, and one is needed."""


class ProviderNotSupported(NotImplementedError):
    """A registered table names a provider Core cannot install from yet."""


def pseudo_root() -> Path:
    """Return the directory installed tables live under.

    This is what ``--pseudo-root`` would be pointed at, so a table Core
    installed and one the user unpacked by hand are indistinguishable.
    """
    return artifact_path("pseudopotentials")


def install_path(table: PseudoTable, root: Path | None = None) -> Path:
    """Return where ``table`` lives once installed."""
    library, source_set = _layout(table)
    return (root or pseudo_root()) / library / source_set


def is_installed(table: PseudoTable, root: Path | None = None) -> bool:
    """Whether ``table`` has pseudopotentials on disk."""
    return any(install_path(table, root).glob("*.upf", case_sensitive=False))


_TABLE_TO_FILE_RELATIVISTIC = {"SR": "scalar", "FR": "full", "NR": "non-relativistic"}
"""Registry vocabulary (whole-table) to UPF vocabulary (per-file), for the stamp."""


def install(
    table: PseudoTable,
    *,
    root: Path | None = None,
    http: HttpClient | None = None,
) -> Path:
    """Install ``table`` from its provider and return its directory.

    Raises:
        ProviderNotSupported: the entry names a provider with no installer.
    """
    if table.provider == "pseudodojo":
        destination = pseudodojo.install(
            table.upstream_table, root=root or pseudo_root(), http=http
        )
    elif table.provider == "materialscloud":
        if not table.record:
            raise ProviderNotSupported(
                f"{table.name} names no record to resolve from the Archive"
            )
        destination = sssp.install(
            table.record, table.upstream_table, root=root or pseudo_root(), http=http
        )
    else:
        raise ProviderNotSupported(
            f"{table.name} is served by {table.provider!r}, which Core cannot install "
            f"from yet. Fetch it from {table.upstream_url} and pass --pseudo-root."
        )

    _stamp_relativistic(destination, table.relativistic)
    return destination


def _stamp_relativistic(destination: Path, relativistic: str) -> None:
    """Record the table's SR/FR classification where cutoff discovery reads it.

    A task selects one pseudopotential library, not a relativistic mode per
    element. Some tables mix UPF-header labels within an otherwise consistent
    table -- SSSP marks its lightest elements (B, Be, Li) ``non-relativistic``
    in their own headers even though the table as a whole is scalar-relativistic
    -- so selection has to trust the table's registered classification rather
    than each file's own header, or it silently drops those elements from every
    scalar-relativistic search. See stfc/goldilocks-core#150.
    """
    sidecar = destination.parent / f"{destination.name}.json"
    data = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    data["_relativistic"] = _TABLE_TO_FILE_RELATIVISTIC[relativistic]
    sidecar.write_text(json.dumps(data, indent=2))


def installed_tables(
    tables: dict[str, PseudoTable] | None = None,
    root: Path | None = None,
) -> tuple[PseudoTable, ...]:
    """Return the registered tables present on disk."""
    registry = tables if tables is not None else load_tables()
    return tuple(t for t in registry.values() if is_installed(t, root))


def require_installed(
    tables: dict[str, PseudoTable] | None = None,
    root: Path | None = None,
) -> tuple[PseudoTable, ...]:
    """Return the installed tables, or explain how to get one.

    Raises:
        NoPseudopotentials: nothing is installed. The message names the default
            table, what it costs, what it is licensed under and what to cite,
            because a user who has just installed Core has no way to know any
            of that.
    """
    installed = installed_tables(tables, root)
    if installed:
        return installed

    default = default_table(tables)
    megabytes = (default.transfer_bytes or 0) / 1e6

    raise NoPseudopotentials(
        "no pseudopotential table is installed.\n\n"
        "  Nothing is downloaded unless you ask. To install the default table:\n\n"
        f"      {INSTALL_COMMAND}\n\n"
        f"  That fetches {default.name}\n"
        f"  ({megabytes:.1f} MB, {default.licence}, from {default.upstream_url}).\n"
        f"  Cite: {default.citation}\n\n"
        f"  To see every table:      {AVAILABLE_COMMAND}\n"
        "  To use one you already have:  --pseudo-root PATH"
    )


def _layout(table: PseudoTable) -> tuple[str, str]:
    """Return the ``(library, source_set)`` directory names for ``table``.

    Selection derives both from the path, so these names are load-bearing
    rather than cosmetic.
    """
    if table.provider == "pseudodojo":
        return pseudodojo.LIBRARY, f"{table.upstream_table}_upf"

    if table.provider == "materialscloud":
        return sssp.LIBRARY, table.upstream_table

    return table.provider, table.upstream_table


def resolve_pseudos(
    root: PathLike | None = None,
    *,
    required: bool = True,
) -> tuple[PseudoMetadata, ...]:
    """Return the pseudopotentials a run should choose from.

    An explicit ``root`` always wins: a user who names a directory means that
    directory, whether or not Core installed anything. Otherwise the installed
    tables are used.

    Args:
        root: an explicit pseudopotential root, usually ``--pseudo-root``.
        required: whether the caller cannot proceed without pseudopotentials.
            Recommending k-points does not need them; writing an input does.

    Raises:
        NoPseudopotentials: ``required`` and nothing is installed. The message
            names the command that fixes it.
    """
    if root is not None:
        return tuple(load_pseudo_metadata(root))

    if required:
        require_installed()
    elif not installed_tables():
        return ()

    return tuple(load_pseudo_metadata(pseudo_root()))
