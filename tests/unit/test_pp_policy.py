from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_policy import PseudoPolicy, apply_pseudo_policy


def test_apply_pseudo_policy_filters_metadata_list() -> None:
    """Apply a simple pseudo policy to a metadata list."""
    metadata_list = [
        PseudoMetadata(
            filepath="a.UPF",
            filename="a.UPF",
            header_format="attr",
            library="pslibrary",
            element="Hg",
            pseudo_type="USPP",
            functional="PBE",
            relativistic="scalar",
            z_valence=12.0,
        ),
        PseudoMetadata(
            filepath="b.UPF",
            filename="b.UPF",
            header_format="attr",
            library="SSSP",
            element="Hg",
            pseudo_type="PAW",
            functional="PBE",
            relativistic="full",
            z_valence=12.0,
        ),
        PseudoMetadata(
            filepath="c.UPF",
            filename="c.UPF",
            header_format="attr",
            library="SSSP",
            element="Hg",
            pseudo_type="PAW",
            functional="LDA",
            relativistic="full",
            z_valence=12.0,
        ),
    ]

    policy = PseudoPolicy(
        relativistic_mode="full",
        preferred_functional="PBE",
        allowed_sources=("SSSP",),
        allowed_pseudo_types=("PAW",),
    )

    selected = apply_pseudo_policy(metadata_list, policy)

    assert len(selected) == 1
    assert selected[0].filename == "b.UPF"


def test_apply_pseudo_policy_compares_canonical_functional_labels() -> None:
    """Apply a PBEsol policy across supported label spellings."""
    metadata = PseudoMetadata(
        filepath="Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        element="Si",
        functional="PBESOL",
    )

    selected = apply_pseudo_policy(
        [metadata],
        PseudoPolicy(preferred_functional="PBE-sol"),
    )

    assert selected == [metadata]
    assert metadata.functional == "PBEsol"
