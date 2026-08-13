"""Console operations over domain-owned runtime asset catalogues."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from goldilocks_core.assets import AssetPreparer, AssetSpec, AssetStore, InstalledAsset
from goldilocks_core.assets.profiles import profile
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.import_pseudodojo import preparer as dojo_preparer
from goldilocks_core.pseudo.import_sssp import preparer as sssp_preparer
from goldilocks_core.pseudo.registry import load_tables


@dataclass(frozen=True, slots=True)
class AssetRegistration:
    """One domain-owned asset declaration and optional normalization step."""

    spec: AssetSpec
    prepare: AssetPreparer | None = None


def catalogue() -> dict[str, AssetRegistration]:
    """Return all assets shipped by the model and pseudopotential domains."""
    registrations = {spec.id: AssetRegistration(spec) for spec in model_asset_specs()}
    for table in load_tables().values():
        prepare = (
            dojo_preparer(table)
            if table.provider == "pseudodojo"
            else sssp_preparer(table)
        )
        registrations[table.id] = AssetRegistration(table.asset, prepare)
    return registrations


def references(
    name: str, entries: Mapping[str, AssetRegistration] | None = None
) -> tuple[AssetRegistration, ...]:
    """Resolve one asset id or an exact shipped profile to registrations."""
    entries = dict(entries or catalogue())
    if name in entries:
        return (entries[name],)
    selected = profile(name)
    resolved: list[AssetRegistration] = []
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
