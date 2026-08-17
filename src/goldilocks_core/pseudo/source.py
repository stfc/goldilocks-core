"""Resolve one explicit pseudopotential metadata source on demand."""

from __future__ import annotations

from typing import Callable

from pymatgen.core import Structure

from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import (
    PathLike,
    PresetRequest,
    PseudoMetadata,
    PseudopotentialRequirements,
    QueryRequest,
)
from goldilocks_core.pseudo.installed import load_installed_table
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.pseudo.registry import PseudoTable, default_table, load_tables

PseudoSource = Callable[
    [Structure, PseudopotentialRequirements], tuple[PseudoMetadata, ...]
]


class PseudoTableMismatch(ValueError):
    """A selected table cannot satisfy the requested scientific constraints."""
    pass


def source_for_request(
    request: PresetRequest | QueryRequest,
    *,
    store: AssetStore,
    registry_path: PathLike | None = None,
) -> PseudoSource:
    """Choose one source resolver using explicit request precedence."""
    if request.pseudo_metadata is not None:
        metadata = request.pseudo_metadata
        return lambda structure, requirements: tuple(metadata)
    if request.pseudo_root is not None:
        root = request.pseudo_root
        return lambda structure, requirements: tuple(load_pseudo_metadata(root))
    table_id = request.pseudo_table
    return lambda structure, requirements: _resolve_installed(
        store, table_id, registry_path, structure, requirements
    )


def _resolve_installed(
    store: AssetStore,
    table_id: str | None,
    registry_path: PathLike | None,
    structure: Structure,
    requirements: PseudopotentialRequirements,
) -> tuple[PseudoMetadata, ...]:
    tables = load_tables(registry_path)
    if table_id is None:
        table = default_table(tables)
    else:
        try:
            table = tables[table_id]
        except KeyError as error:
            choices = ", ".join(sorted(tables))
            raise PseudoTableMismatch(
                f"unknown pseudopotential table {table_id!r}; available: {choices}"
            ) from error

    elements = {element.symbol for element in structure.composition.elements}
    problems = _table_problems(table, elements, requirements)
    if problems:
        matches = [
            candidate.id
            for candidate in tables.values()
            if not _table_problems(candidate, elements, requirements)
        ]
        alternatives = ", ".join(sorted(matches)) or "none"
        raise PseudoTableMismatch(
            f"pseudopotential table {table.id!r} does not satisfy the request: "
            f"{'; '.join(problems)}; matching tables: {alternatives}"
        )

    installed = store.resolve(table.asset.id, table.asset.version)
    return load_installed_table(installed, table=table)


def _table_problems(
    table: PseudoTable,
    elements: set[str],
    requirements: PseudopotentialRequirements,
) -> list[str]:
    problems: list[str] = []
    if table.functional != requirements.functional:
        problems.append(
            f"functional is {table.functional}, requested {requirements.functional}"
        )
    if table.accuracy != requirements.accuracy:
        problems.append(
            f"accuracy is {table.accuracy}, requested {requirements.accuracy}"
        )
    if table.relativistic != requirements.relativistic:
        problems.append(
            f"relativistic treatment is {table.relativistic}, "
            f"requested {requirements.relativistic}"
        )
    missing = sorted(elements - set(table.elements))
    if missing:
        problems.append("missing elements " + ", ".join(missing))
    return problems
