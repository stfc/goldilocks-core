from __future__ import annotations

import pytest

from goldilocks_core.inputs.hpc import (
    InvalidHpcProfile,
    list_hpc_profiles,
    load_hpc_profile,
    resolve_hpc_profile,
)


def test_loads_the_real_scarf_profile() -> None:
    profile = load_hpc_profile("scarf")

    assert profile.scheduler == "slurm"
    assert profile.launcher == "srun"
    assert profile.modules["quantum_espresso"] == ("QuantumESPRESSO/7.5-foss-2025a",)
    # #133: nothing reads a ScaLAPACK flag; pw.x picks ndiag itself.
    assert not hasattr(profile, "has_scalapack")


def test_list_hpc_profiles_includes_scarf_and_is_sorted() -> None:
    names = list_hpc_profiles()

    assert "scarf" in names
    assert names == tuple(sorted(names))
    assert all(name == load_hpc_profile(name).name for name in names)


def test_scarf_partition_is_the_default() -> None:
    profile = load_hpc_profile("scarf")

    default = profile.default_partition()

    assert default.name == "scarf"
    assert default.hardware.max_walltime_h == 168


def test_partition_overrides_inherit_unspecified_fields_from_hardware_baseline() -> (
    None
):
    profile = load_hpc_profile("scarf")

    devel = profile.partition("devel")

    assert devel.hardware.max_walltime_h == 12  # overridden
    assert devel.hardware.cores_per_node == 64  # inherited from [hardware]
    assert devel.hardware.mem_per_node_gb == 250  # inherited from [hardware]


def test_gpu_partition_has_its_own_full_hardware_spec() -> None:
    profile = load_hpc_profile("scarf")

    gpu = profile.partition("gpu")

    assert gpu.hardware.cores_per_node == 32
    assert gpu.hardware.max_nodes == 12
    assert gpu.hardware.max_walltime_h == 48


def test_unknown_partition_raises_with_available_choices() -> None:
    profile = load_hpc_profile("scarf")

    with pytest.raises(ValueError, match="scarf") as excinfo:
        profile.partition("does-not-exist")
    assert "does-not-exist" in str(excinfo.value)


def test_unknown_profile_name_raises_invalid_hpc_profile() -> None:
    with pytest.raises(InvalidHpcProfile):
        load_hpc_profile("not-a-real-machine")


def test_a_profile_with_two_default_partitions_is_rejected(
    tmp_path, monkeypatch
) -> None:
    import goldilocks_core.inputs.hpc as hpc_module

    contents = """
    scheduler = "slurm"
    launcher = "srun"
    [hardware]
    cores_per_node = 32
    mem_per_node_gb = 100
    max_nodes = 10
    max_walltime_h = 24
    [partitions.a]
    default = true
    [partitions.b]
    default = true
    """
    (tmp_path / "broken.toml").write_text(contents)

    class _FakeResources:
        @staticmethod
        def joinpath(filename):
            return tmp_path / filename

    monkeypatch.setattr(hpc_module.resources, "files", lambda _pkg: _FakeResources())

    with pytest.raises(InvalidHpcProfile, match="exactly one default"):
        load_hpc_profile("broken")


def test_resolve_hpc_profile_uses_the_explicit_name_when_given() -> None:
    profile = resolve_hpc_profile("scarf")

    assert profile.name == "scarf"


def test_resolve_hpc_profile_defaults_when_exactly_one_is_installed() -> None:
    assert len(list_hpc_profiles()) == 1, "test assumes exactly one shipped profile"

    profile = resolve_hpc_profile(None)

    assert profile.name == "scarf"


def test_resolve_hpc_profile_rejects_an_unknown_name() -> None:
    with pytest.raises(InvalidHpcProfile):
        resolve_hpc_profile("does-not-exist")
