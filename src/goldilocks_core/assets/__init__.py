"""Shared lifecycle for immutable runtime assets."""

from goldilocks_core.assets.records import (
    AssetFile,
    AssetReference,
    AssetSpec,
    InstalledAsset,
    InstalledFile,
    RuntimeProfile,
)
from goldilocks_core.assets.store import (
    ASSET_ROOT_ENV,
    AssetCorrupt,
    AssetNotInstalled,
    AssetPreparer,
    AssetStore,
    asset_root,
)

__all__ = [
    "ASSET_ROOT_ENV",
    "AssetCorrupt",
    "AssetFile",
    "AssetNotInstalled",
    "AssetPreparer",
    "AssetReference",
    "AssetSpec",
    "AssetStore",
    "InstalledAsset",
    "InstalledFile",
    "RuntimeProfile",
    "asset_root",
]
