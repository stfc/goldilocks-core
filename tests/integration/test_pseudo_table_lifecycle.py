"""End-to-end pseudopotential table lifecycle over the shipped registry.

Every registered table is installed into a fresh asset store with fabricated
payloads, then resolved and loaded back through the strict reader. This keeps
write/read manifest drift (asset ids, versions, element coverage) from
reaching a fresh user install.

Trimmed for v2 epic 9 (#9): a second test here used to also resolve the
default table through v1's ``pseudo.source.PseudoResolution`` -- v2's
own default/automatic table selection (``select_pseudopotential_table``)
has its own dedicated tests in ``test_advisors_pseudo_selection.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from goldilocks_core.assets.pseudopotentials.importers import (
    load_installed_table,
    write_table_manifest,
)
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable, load_tables
from goldilocks_core.assets.records import AssetFile
from goldilocks_core.assets.store import AssetStore

pytestmark = pytest.mark.integration

REGISTRY_TABLES = load_tables()


@pytest.fixture(autouse=True)
def no_network_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace remote acquisition with local bytes; payloads stay fabricated."""
    from goldilocks_core.assets import store as store_module

    def fake_download(file: AssetFile, destination: Path) -> None:
        destination.write_bytes(b"synthetic source: " + file.role.encode())

    monkeypatch.setattr(store_module, "download", fake_download)


def fabricated_preparer(table: PseudoTable) -> Callable[[dict[str, Path], Path], None]:
    """Build a network-free preparer that writes real manifest entries."""

    def prepare(sources: dict[str, Path], destination: Path) -> None:
        entries = []
        for element in table.elements:
            payload = f"synthetic pseudopotential for {element}".encode()
            relative_path = f"pseudos/{element}.upf"
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            entries.append(
                {
                    "element": element,
                    "path": relative_path,
                    "md5": hashlib.md5(payload).hexdigest(),
                    "header_format": "attr",
                    "upf_relativistic": table.relativistic,
                    "pseudo_type": "NC",
                    "z_valence": 4.0,
                    "ecutwfc_ry": 35.0,
                    "ecutrho_ry": 140.0,
                    "source_identifier": None,
                    "frozen_4f_core": False,
                }
            )
        write_table_manifest(destination, table, entries)

    return prepare


@pytest.mark.parametrize(
    "table", list(REGISTRY_TABLES.values()), ids=list(REGISTRY_TABLES)
)
def test_every_registered_table_installs_and_loads(
    tmp_path: Path, table: PseudoTable
) -> None:
    """Install, resolve, and strictly load one shipped registry table."""
    store = AssetStore(tmp_path / "store")

    installed = store.install(table.asset, fabricated_preparer(table))
    metadata = load_installed_table(installed, table=table)

    assert {item.element for item in metadata} == set(table.elements)
    assert metadata[0].table_id == table.asset.id
    assert metadata[0].cutoffs is not None
