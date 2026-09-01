"""Shipped runtime profiles composed from exact domain asset versions."""

from goldilocks_core.assets.records import AssetReference, RuntimeProfile

DEFAULT_PROFILE = RuntimeProfile(
    name="default",
    assets=(
        AssetReference("models/qrf-kpoints", "QRF95"),
        AssetReference("models/metallicity-cgcnn", "1"),
        AssetReference("pseudopotentials/pseudodojo-pbesol-efficiency-sr", "0.4"),
    ),
)

PROFILES = {DEFAULT_PROFILE.name: DEFAULT_PROFILE}


def profile(name: str) -> RuntimeProfile:
    """Return a shipped profile by name."""
    try:
        return PROFILES[name]
    except KeyError as error:
        raise KeyError(f"unknown runtime profile: {name}") from error
