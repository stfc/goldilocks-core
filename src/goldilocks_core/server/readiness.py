from __future__ import annotations

import threading
from dataclasses import dataclass

from goldilocks_core.assets import (
    AssetCorrupt,
    AssetInstallation,
    AssetNotInstalled,
    AssetStore,
)
from goldilocks_core.assets.runtime import WORKBENCH_PROFILE, catalogue, references
from goldilocks_core.contracts import PathLike


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    asset_count: int
    asset_id: str | None = None
    version: str | None = None
    state: str | None = None


class AssetReadiness:
    def __init__(
        self,
        store: AssetStore,
        *,
        model_registry_path: PathLike | None = None,
        pseudo_registry_path: PathLike | None = None,
    ) -> None:
        self._store = store
        entries = catalogue(
            model_registry_path=model_registry_path,
            pseudo_registry_path=pseudo_registry_path,
        )
        self._installations: tuple[AssetInstallation, ...] = references(
            WORKBENCH_PROFILE, entries
        )
        self._lock = threading.Lock()
        self._report: ReadinessReport | None = None

    def check(self) -> ReadinessReport:
        with self._lock:
            if self._report is None:
                self._report = self._verify_profile()
            return self._report

    def _verify_profile(self) -> ReadinessReport:
        installations = self._installations
        for installation in installations:
            spec = installation.spec
            try:
                self._store.verify_spec(spec)
            except AssetNotInstalled:
                return ReadinessReport(
                    ready=False,
                    asset_count=len(installations),
                    asset_id=spec.id,
                    version=spec.version,
                    state="missing",
                )
            except AssetCorrupt:
                return ReadinessReport(
                    ready=False,
                    asset_count=len(installations),
                    asset_id=spec.id,
                    version=spec.version,
                    state="corrupt",
                )
        return ReadinessReport(ready=True, asset_count=len(installations))
