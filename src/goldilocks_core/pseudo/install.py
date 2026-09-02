from __future__ import annotations

from collections.abc import Callable, Mapping

from goldilocks_core.assets.records import AssetInstallation, AssetPreparer
from goldilocks_core.pseudo.import_pseudodojo import preparer as dojo_preparer
from goldilocks_core.pseudo.import_sssp import preparer as sssp_preparer
from goldilocks_core.pseudo.registry import (
    InvalidPseudoRegistry,
    PseudoTable,
    load_tables,
)
from goldilocks_core.types import PathLike

_PREPARERS: Mapping[str, Callable[[PseudoTable], AssetPreparer]] = {
    "pseudodojo": dojo_preparer,
    "sssp": sssp_preparer,
}


def installation_for(table: PseudoTable) -> AssetInstallation:
    try:
        prepare = _PREPARERS[table.provider]
    except KeyError as error:
        raise InvalidPseudoRegistry(
            f"table {table.id!r} has unsupported provider {table.provider!r}"
        ) from error
    return AssetInstallation(table.asset, prepare(table))


def table_installations(
    path: PathLike | None = None,
) -> tuple[AssetInstallation, ...]:
    return tuple(installation_for(table) for table in load_tables(path).values())
