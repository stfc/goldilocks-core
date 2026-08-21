from __future__ import annotations

from typing import Callable

from pymatgen.core import Element, Structure

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
from goldilocks_core.pseudo.registry import PseudoTable, load_tables

PseudoSource = Callable[
    [Structure, PseudopotentialRequirements], tuple[PseudoMetadata, ...]
]


class PseudoTableMismatch(ValueError):
    pass


def source_for_request(
    request: PresetRequest | QueryRequest,
    *,
    store: AssetStore,
    registry_path: PathLike | None = None,
) -> PseudoSource:
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
    elements = {element.symbol for element in structure.composition.elements}
    table = select_compatible_table(
        tables,
        table_id=table_id,
        elements=elements,
        requirements=requirements,
    )

    installed = store.resolve_spec(table.asset)
    return load_installed_table(installed, table=table)


def select_compatible_table(
    tables: dict[str, PseudoTable],
    *,
    table_id: str | None,
    elements: set[str],
    requirements: PseudopotentialRequirements,
) -> PseudoTable:
    """Select an explicit or preferred compatible pseudopotential table."""
    if table_id is None:
        return _automatic_table(tables, elements, requirements)
    try:
        table = tables[table_id]
    except KeyError as error:
        choices = ", ".join(sorted(tables))
        raise PseudoTableMismatch(
            f"unknown pseudopotential table {table_id!r}; available: {choices}"
        ) from error

    problems = _table_problems(table, elements, requirements)
    if not problems:
        return table
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


def is_table_eligible_for_elements(table: PseudoTable, elements: set[str]) -> bool:
    """Return whether a table may serve every element under Core policy."""
    return all(element in table.elements for element in elements) and (
        not _requires_sssp(elements) or table.provider == "sssp"
    )


def _automatic_table(
    tables: dict[str, PseudoTable],
    elements: set[str],
    requirements: PseudopotentialRequirements,
) -> PseudoTable:
    matches = [
        table
        for table in tables.values()
        if not _table_problems(table, elements, requirements)
    ]
    if not matches:
        requested = (
            f"{requirements.functional} {requirements.accuracy} "
            f"{requirements.relativistic}"
        )
        raise PseudoTableMismatch(
            f"no pseudopotential table satisfies {requested} for "
            + ", ".join(sorted(elements))
        )
    provider = "sssp" if _requires_sssp(elements) else "pseudodojo"
    return min(
        matches,
        key=lambda table: (table.provider != provider, table.id),
    )


def _requires_sssp(elements: set[str]) -> bool:
    return any(
        element.is_lanthanoid or element.is_actinoid
        for element in map(Element, elements)
    )


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
    if _requires_sssp(elements) and table.provider != "sssp":
        problems.append("lanthanide and actinide elements require an SSSP table")
    missing = sorted(elements - set(table.elements))
    if missing:
        problems.append("missing elements " + ", ".join(missing))
    return problems
