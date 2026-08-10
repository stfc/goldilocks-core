"""Tests for installing registered tables and reporting what is installed."""

from __future__ import annotations

import dataclasses

import pytest

from goldilocks_core.artifacts import cache
from goldilocks_core.pseudo import install as installer
from goldilocks_core.pseudo.table_registry import load_tables


@pytest.fixture
def registry():
    return load_tables()


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv(cache.CACHE_ENV, str(tmp_path / "cache"))


def _pretend_installed(table, contents=("Si.upf",)):
    directory = installer.install_path(table)
    directory.mkdir(parents=True, exist_ok=True)
    for name in contents:
        (directory / name).write_bytes(b"pseudo")
    return directory


def test_install_path_uses_the_layout_selection_derives_from(registry):
    table = registry["pseudodojo-pbesol-efficiency"]

    path = installer.install_path(table)

    assert path.parent.name == "pseudodojo"
    assert path.name == "nc-sr-04_pbesol_standard_upf"
    assert path.parent.parent == installer.pseudo_root()


def test_install_path_uses_the_upstream_name_not_ours(registry):
    """The directory has to match what a hand-installed table would look like."""
    table = registry["pseudodojo-pbesol-efficiency"]

    assert table.name not in str(installer.install_path(table))
    assert table.upstream_table in str(installer.install_path(table))


def test_an_sssp_table_installs_where_cutoff_discovery_looks(registry):
    """The parser wants `SSSP*` directories with a sidecar named after them."""
    table = registry["sssp-pbesol-efficiency"]

    path = installer.install_path(table)

    assert path.parent.name == "sssp"
    assert path.name.startswith("SSSP")


def test_is_installed_sees_uppercase_extensions(registry):
    """SSSP ships a mix of .upf and .UPF; half the table is invisible otherwise."""
    table = registry["sssp-pbesol-efficiency"]
    _pretend_installed(table, contents=("Si.UPF", "Ge.UPF"))

    assert installer.is_installed(table)


def test_nothing_is_installed_on_a_fresh_cache(registry):
    assert installer.installed_tables(registry) == ()


def test_installed_tables_reports_only_what_is_present(registry):
    _pretend_installed(registry["pseudodojo-pbe-lanthanides"])

    installed = installer.installed_tables(registry)

    assert [t.name for t in installed] == ["pseudodojo-pbe-lanthanides"]


def test_require_installed_explains_how_to_get_a_table(registry):
    with pytest.raises(installer.NoPseudopotentials) as raised:
        installer.require_installed(registry)

    message = str(raised.value)
    assert installer.INSTALL_COMMAND in message
    assert installer.AVAILABLE_COMMAND in message
    assert "--pseudo-root" in message


def test_the_missing_table_message_carries_terms_and_a_citation(registry):
    """A user who just installed Core has no other way to learn either."""
    with pytest.raises(installer.NoPseudopotentials) as raised:
        installer.require_installed(registry)

    default = registry["pseudodojo-pbesol-efficiency"]
    message = str(raised.value)
    assert default.name in message
    assert default.licence in message
    assert default.citation in message
    assert "5.2 MB" in message


def test_require_installed_is_silent_once_a_table_is_present(registry):
    _pretend_installed(registry["pseudodojo-pbesol-efficiency"])

    assert installer.require_installed(registry)


def test_an_unknown_provider_names_the_manual_route(registry):
    stranger = dataclasses.replace(
        registry["pseudodojo-pbesol-efficiency"], provider="somewhere-else"
    )

    with pytest.raises(installer.ProviderNotSupported, match="--pseudo-root"):
        installer.install(stranger)


def test_every_registered_provider_has_an_installer(registry):
    """A table listed but not installable is a promise the CLI cannot keep."""
    for table in registry.values():
        assert table.provider in {"pseudodojo", "materialscloud"}
