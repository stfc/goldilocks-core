from goldilocks_core.assets.records import AssetReference, RuntimeProfile

DEFAULT_PROFILE = RuntimeProfile(
    name="default",
    assets=(
        AssetReference("models/qrf-kpoints", "QRF95"),
        AssetReference("models/metallicity-cgcnn", "1"),
        AssetReference("models/metallicity-is-metal", "1.0"),
        AssetReference("pseudopotentials/pseudodojo-pbesol-efficiency-sr", "0.4"),
    ),
)

PROFILES = {DEFAULT_PROFILE.name: DEFAULT_PROFILE}


def profile(name: str) -> RuntimeProfile:
    try:
        return PROFILES[name]
    except KeyError as error:
        raise KeyError(f"unknown runtime profile: {name}") from error
