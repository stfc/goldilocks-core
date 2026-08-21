from __future__ import annotations

from collections.abc import Mapping

from goldilocks_core.assets import AssetInstallation, AssetStore, InstalledAsset
from goldilocks_core.assets.profiles import profile
from goldilocks_core.contracts import PathLike
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.install import table_installations

WORKBENCH_PROFILE = "workbench"


def catalogue(
    *,
    model_registry_path: PathLike | None = None,
    pseudo_registry_path: PathLike | None = None,
) -> dict[str, AssetInstallation]:
    installations = (
        *(AssetInstallation(spec) for spec in model_asset_specs(model_registry_path)),
        *table_installations(pseudo_registry_path),
    )
    registrations: dict[str, AssetInstallation] = {}
    for installation in installations:
        asset_id = installation.spec.id
        if asset_id in registrations:
            raise ValueError(f"duplicate runtime asset id: {asset_id}")
        registrations[asset_id] = installation
    return registrations


def references(
    name: str, entries: Mapping[str, AssetInstallation] | None = None
) -> tuple[AssetInstallation, ...]:
    entries = dict(entries or catalogue())
    if name in entries:
        return (entries[name],)
    if name == WORKBENCH_PROFILE:
        return tuple(entries[asset_id] for asset_id in sorted(entries))
    selected = profile(name)
    resolved: list[AssetInstallation] = []
    for reference in selected.assets:
        registration = entries.get(reference.id)
        if registration is None or registration.spec.version != reference.version:
            raise KeyError(
                f"profile {name!r} references unavailable asset "
                f"{reference.id}@{reference.version}"
            )
        resolved.append(registration)
    return tuple(resolved)


def install(
    name: str, *, store: AssetStore | None = None
) -> tuple[InstalledAsset, ...]:
    target = store or AssetStore()
    return tuple(
        target.install(registration.spec, registration.prepare)
        for registration in references(name)
    )


def statuses(
    name: str, *, store: AssetStore | None = None
) -> tuple[tuple[str, str, str], ...]:
    target = store or AssetStore()
    return tuple(
        (
            registration.spec.id,
            registration.spec.version,
            target.status_spec(registration.spec),
        )
        for registration in references(name)
    )


def verify(name: str, *, store: AssetStore | None = None) -> tuple[InstalledAsset, ...]:
    target = store or AssetStore()
    return tuple(
        target.verify_spec(registration.spec) for registration in references(name)
    )
