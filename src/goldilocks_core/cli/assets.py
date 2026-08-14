"""Console operations over domain-owned runtime asset catalogues."""

from __future__ import annotations

from collections.abc import Mapping

from goldilocks_core.assets import AssetInstallation, AssetStore, InstalledAsset
from goldilocks_core.assets.profiles import profile
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.install import table_installations


def catalogue() -> dict[str, AssetInstallation]:
    """Merge domain installations and reject duplicate asset identifiers."""
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
    """Resolve one asset id or an exact shipped profile to registrations."""
    entries = dict(entries or catalogue())
    if name in entries:
        return (entries[name],)
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
    """Install one asset or every exact asset in a shipped profile."""
    target = store or AssetStore()
    return tuple(
        target.install(registration.spec, registration.prepare)
        for registration in references(name)
    )


def statuses(
    name: str, *, store: AssetStore | None = None
) -> tuple[tuple[str, str, str], ...]:
    """Return id, version, and integrity status for an asset or profile."""
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
    """Verify one asset or every exact asset in a shipped profile."""
    target = store or AssetStore()
    return tuple(
        target.verify(registration.spec.id, registration.spec.version)
        for registration in references(name)
    )
