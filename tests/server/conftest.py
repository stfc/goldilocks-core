"""Shared fixtures for HTTP/MCP tests (v2 epic 8, #8).

Unlike v1's own conftest (Service/Runtime/GraphHandler/TaskGraph, all
gone in v2), these tests run against a real, already-resolvable
pseudopotential table via the machine's actual asset store -- same
convention as ``tests/integration/test_cli_v2.py``'s ``real_assets``
fixture -- rather than hand-building a synthetic asset installation
for every test file that needs one. The exception is
``silicon_fixture_table``: one synthetic table, for the few ``run``
tests that must also run in CI, which installs no assets.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import sssp_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.runtime import statuses
from goldilocks_core.assets.store import AssetStore, asset_root
from goldilocks_core.examples.structures import structure

REAL_ASSET_ROOT = asset_root()


def _default_profile_installed() -> bool:
    store = AssetStore(REAL_ASSET_ROOT)
    return all(state == "installed" for _, _, state in statuses("default", store=store))


@pytest.fixture
def real_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _default_profile_installed():
        pytest.skip(f"default asset profile not installed at {REAL_ASSET_ROOT}")
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(REAL_ASSET_ROOT))


@pytest.fixture
def silicon_cif() -> str:
    return structure("Si.cif").read_text()


@pytest.fixture
def silicon_fixture_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The synthetic Si SSSP table (``support.sssp_fixture_table_spec``),
    installed into this test's isolated asset root and registered as the
    only table: ``run`` then completes for ``silicon_cif`` without the real
    assets, which CI does not install."""
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources")
    AssetStore().install(spec, sssp_preparer(registry_table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {registry_table.id: registry_table},
    )
