from __future__ import annotations

import threading
from dataclasses import dataclass

from goldilocks_core.assets import AssetCorrupt, AssetNotInstalled, AssetStore
from goldilocks_core.assets.runtime import WORKBENCH_PROFILE, references


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    asset_count: int
    asset_id: str | None = None
    version: str | None = None
    state: str | None = None
    message: str | None = None


class AssetReadiness:
    def __init__(self, store: AssetStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._report: ReadinessReport | None = None

    def check(self) -> ReadinessReport:
        with self._lock:
            if self._report is None:
                self._report = self._verify_profile()
            return self._report

    def _verify_profile(self) -> ReadinessReport:
        installations = references(WORKBENCH_PROFILE)
        for installation in installations:
            spec = installation.spec
            try:
                self._store.verify(spec.id, spec.version)
            except AssetNotInstalled as error:
                return ReadinessReport(
                    ready=False,
                    asset_count=len(installations),
                    asset_id=spec.id,
                    version=spec.version,
                    state="missing",
                    message=str(error),
                )
            except AssetCorrupt as error:
                return ReadinessReport(
                    ready=False,
                    asset_count=len(installations),
                    asset_id=spec.id,
                    version=spec.version,
                    state="corrupt",
                    message=str(error),
                )
        return ReadinessReport(ready=True, asset_count=len(installations))
