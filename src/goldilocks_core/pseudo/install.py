"""Install registered pseudopotential tables through the shared asset store."""

from __future__ import annotations

from goldilocks_core.assets import AssetStore, InstalledAsset
from goldilocks_core.pseudo.import_pseudodojo import preparer as dojo_preparer
from goldilocks_core.pseudo.import_sssp import preparer as sssp_preparer
from goldilocks_core.pseudo.registry import load_tables


def install_table(table_id: str, *, store: AssetStore | None = None) -> InstalledAsset:
    """Install one registered table and return its verified asset."""
    table = load_tables()[table_id]
    prepare = (
        dojo_preparer(table) if table.provider == "pseudodojo" else sssp_preparer(table)
    )
    return (store or AssetStore()).install(table.asset, prepare)
