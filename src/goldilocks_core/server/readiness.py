from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from goldilocks_core.assets.records import AssetInstallation
from goldilocks_core.assets.runtime import WORKBENCH_PROFILE, catalogue, references
from goldilocks_core.assets.store import (
    MANIFEST_FILENAME,
    AssetCorrupt,
    AssetNotInstalled,
    AssetStore,
)
from goldilocks_core.types import PathLike


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
        self._state: tuple[tuple[str, int, int, int], ...] | None = None
        self._report: ReadinessReport | None = None

    def check(self) -> ReadinessReport:
        with self._lock:
            state = self._filesystem_state()
            if state != self._state:
                self._report = self._verify_profile()
                self._state = self._filesystem_state()
            assert self._report is not None
            return self._report

    def _filesystem_state(self) -> tuple[tuple[str, int, int, int], ...]:
        """Stat exactly the files the installed manifest lists, not a
        full ``rglob`` of the tree (v2 epic 8, #8, issue evidence #4:
        v1 did a full recursive walk on every single ``/ready`` call).
        Cost is proportional to file count, same as before, but without
        ``rglob``'s directory-traversal/sorting overhead on top of that
        count -- the manifest is the same file ``AssetStore.verify``
        already trusts as the definitive list of what an installation
        should contain, so a corrupted/replaced listed file is still
        caught; a missing/unreadable manifest is treated as changed
        state, which forces the real ``verify_spec`` to run and report
        exactly why.

        Accepted narrowing versus the old ``rglob``-based check: a file
        *added* under a nested subdirectory that the manifest never
        listed will not itself flip this state (only the top-level
        ``root`` entry's own mtime would, and only if the extra file
        landed directly inside ``root``). ``verify_spec``'s own
        directory-listing-vs-manifest comparison still catches that the
        next time it actually runs; this cache's job is only to decide
        *when* to run it, not to replace it."""
        state: list[tuple[str, int, int, int]] = []
        for installation in self._installations:
            spec = installation.spec
            root = self._store.root / spec.id / spec.version
            manifest_path = root / MANIFEST_FILENAME
            paths = [root, manifest_path]
            paths.extend(
                root / relative for relative in _manifest_file_paths(manifest_path)
            )
            for path in paths:
                try:
                    status = path.lstat()
                    state.append(
                        (str(path), status.st_mode, status.st_size, status.st_mtime_ns)
                    )
                except OSError:
                    state.append((str(path), -1, -1, -1))
        return tuple(state)

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


def _manifest_file_paths(manifest_path: Path) -> tuple[str, ...]:
    """Best-effort, tolerant read of a manifest's file list -- deliberately
    not ``assets.store``'s own ``_read_manifest``, which raises
    ``AssetCorrupt``/``ValueError`` on any mismatch: this is only a cache
    -invalidation signal, so a missing/malformed manifest here should
    just look like "state changed" (empty list -> only the manifest's
    own stat contributes), not raise -- the real validation still
    happens in ``_verify_profile`` via ``verify_spec``."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return tuple(entry["path"] for entry in data["files"])
    except (OSError, ValueError, KeyError, TypeError):
        return ()
