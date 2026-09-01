from __future__ import annotations

from collections.abc import Mapping

from goldilocks_core.assets import AssetInstallation, AssetStore, InstalledAsset
from goldilocks_core.assets.profiles import profile
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.install import table_installations
from goldilocks_core.pseudo.registry import load_tables


def catalogue() -> dict[str, AssetInstallation]:
    installations = (
        *(AssetInstallation(spec) for spec in model_asset_specs()),
        *table_installations(),
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
    table_reference = _table_reference(name, entries)
    if table_reference is not None:
        return (table_reference,)
    try:
        selected = profile(name)
    except KeyError as error:
        raise KeyError(
            f"unknown asset {name!r}; use an asset id, a registry table id, "
            "or a shipped profile name"
        ) from error
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


def _table_reference(
    name: str, entries: Mapping[str, AssetInstallation]
) -> AssetInstallation | None:
    try:
        table = load_tables()[name]
    except KeyError:
        return None
    return entries.get(table.asset.id)


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
            target.status(registration.spec.id, registration.spec.version),
        )
        for registration in references(name)
    )


def verify(name: str, *, store: AssetStore | None = None) -> tuple[InstalledAsset, ...]:
    target = store or AssetStore()
    return tuple(
        target.verify(registration.spec.id, registration.spec.version)
        for registration in references(name)
    )
