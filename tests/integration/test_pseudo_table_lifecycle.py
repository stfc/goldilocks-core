"""End-to-end pseudopotential table lifecycle over the shipped registry.

Every registered table is installed into a fresh asset store with fabricated
payloads, then resolved and loaded back through the strict reader. This keeps
write/read manifest drift (asset ids, versions, element coverage) from
reaching a fresh user install.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.pseudo import PseudopotentialRequirements
from goldilocks_core.assets import AssetFile, AssetStore
from goldilocks_core.calculation import CalculationHints
from goldilocks_core.io.structures import InMemoryStructureSource
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.installed import load_installed_table, write_table_manifest
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.registry import PseudoTable, default_table, load_tables
from goldilocks_core.pseudo.source import source_for_draft
from goldilocks_core.request import CalculationDraft

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


def test_default_table_serves_a_fresh_install(tmp_path: Path) -> None:
    """The unset-pseudo-fields request path resolves the shipped default."""
    table = default_table(load_tables())
    store = AssetStore(tmp_path / "store")
    store.install(table.asset, fabricated_preparer(table))

    structure = Structure(
        Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    )
    draft = CalculationDraft(
        structure=InMemoryStructureSource(structure),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
    )
    requirements = PseudopotentialRequirements(
        functional=table.functional,
        accuracy=table.accuracy,
        pseudo_type=None,
        relativistic=table.relativistic,
        provenance=Provenance(
            source="default",
            reason="no explicit pseudopotential source in the request",
            data_source="shipped default table",
        ),
    )

    resolver = source_for_draft(draft, store=store)
    metadata: tuple[PseudoMetadata, ...] = resolver(structure, requirements)

    assert {item.element for item in metadata} >= {"Si"}
    assert metadata[0].table_id == table.asset.id
