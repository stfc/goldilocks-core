"""Tests for installing registered tables and reporting what is installed."""

from __future__ import annotations

import dataclasses
import json

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


def _upf(element: str) -> str:
    """The smallest UPF the parser accepts."""
    return (
        "<UPF>"
        f'<PP_HEADER element="{element}" pseudo_type="NC" functional="PBEsol" '
        'relativistic="scalar" z_valence="4.0" />'
        "</UPF>"
    )


def _pretend_installed(table, contents=("Si.upf",)):
    directory = installer.install_path(table)
    directory.mkdir(parents=True, exist_ok=True)
    for name in contents:
        (directory / name).write_text(_upf(name.split(".")[0]))
    return directory


def test_install_path_uses_the_layout_selection_derives_from(registry):
    table = registry["pseudodojo-pbesol-efficiency-sr"]

    path = installer.install_path(table)

    assert path.parent.name == "pseudodojo"
    assert path.name == "nc-sr-04_pbesol_standard_upf"
    assert path.parent.parent == installer.pseudo_root()


def test_install_path_uses_the_upstream_name_not_ours(registry):
    """The directory has to match what a hand-installed table would look like."""
    table = registry["pseudodojo-pbesol-efficiency-sr"]

    assert table.name not in str(installer.install_path(table))
    assert table.upstream_table in str(installer.install_path(table))


def test_an_sssp_table_installs_where_cutoff_discovery_looks(registry):
    """The parser wants `SSSP*` directories with a sidecar named after them."""
    table = registry["sssp-pbesol-efficiency-sr"]

    path = installer.install_path(table)

    assert path.parent.name == "sssp"
    assert path.name.startswith("SSSP")


def test_is_installed_sees_uppercase_extensions(registry):
    """SSSP ships a mix of .upf and .UPF; half the table is invisible otherwise."""
    table = registry["sssp-pbesol-efficiency-sr"]
    _pretend_installed(table, contents=("Si.UPF", "Ge.UPF"))

    assert installer.is_installed(table)


def test_nothing_is_installed_on_a_fresh_cache(registry):
    assert installer.installed_tables(registry) == ()


def test_installed_tables_reports_only_what_is_present(registry):
    _pretend_installed(registry["pseudodojo-pbe-lanthanides-sr"])

    installed = installer.installed_tables(registry)

    assert [t.name for t in installed] == ["pseudodojo-pbe-lanthanides-sr"]


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

    default = registry["pseudodojo-pbesol-efficiency-sr"]
    message = str(raised.value)
    assert default.name in message
    assert default.licence in message
    assert default.citation in message
    assert "5.2 MB" in message


def test_require_installed_is_silent_once_a_table_is_present(registry):
    _pretend_installed(registry["pseudodojo-pbesol-efficiency-sr"])

    assert installer.require_installed(registry)


def test_an_unknown_provider_names_the_manual_route(registry):
    stranger = dataclasses.replace(
        registry["pseudodojo-pbesol-efficiency-sr"], provider="somewhere-else"
    )

    with pytest.raises(installer.ProviderNotSupported, match="--pseudo-root"):
        installer.install(stranger)


def test_install_stamps_the_tables_relativistic_classification(monkeypatch, registry):
    """Selection trusts the table's registered classification, not each header."""
    table = registry["pseudodojo-pbesol-efficiency-sr"]
    destination = installer.install_path(table)

    def _fake_provider_install(upstream_table, *, root, http):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "Si.upf").write_text(_upf("Si"))
        (destination.parent / f"{destination.name}.json").write_text(
            json.dumps({"Si": {"cutoff_wfc": 48.0, "cutoff_rho": 192.0}})
        )
        return destination

    monkeypatch.setattr(installer.pseudodojo, "install", _fake_provider_install)

    installer.install(table)

    sidecar = destination.parent / f"{destination.name}.json"
    written = json.loads(sidecar.read_text())
    assert written["_relativistic"] == "scalar"
    assert written["_accuracy"] == "efficiency"
    assert written["Si"]["cutoff_wfc"] == 48.0


def test_install_stamps_the_tables_accuracy_tier(monkeypatch, registry):
    """PseudoDojo's own standard/stringent naming never says efficiency/precision."""
    table = registry["pseudodojo-pbesol-precision-sr"]
    destination = installer.install_path(table)

    def _fake_provider_install(*_args, **_kwargs):
        destination.mkdir(parents=True, exist_ok=True)
        (destination.parent / f"{destination.name}.json").write_text("{}")
        return destination

    monkeypatch.setattr(installer.pseudodojo, "install", _fake_provider_install)

    installer.install(table)

    sidecar = destination.parent / f"{destination.name}.json"
    assert json.loads(sidecar.read_text())["_accuracy"] == "precision"


def test_install_stamps_full_for_a_fully_relativistic_table(monkeypatch, registry):
    fr_table = next(t for t in registry.values() if t.relativistic == "FR")
    destination = installer.install_path(fr_table)

    def _fake_provider_install(*_args, **_kwargs):
        destination.mkdir(parents=True, exist_ok=True)
        (destination.parent / f"{destination.name}.json").write_text("{}")
        return destination

    monkeypatch.setattr(installer.pseudodojo, "install", _fake_provider_install)

    installer.install(fr_table)

    sidecar = destination.parent / f"{destination.name}.json"
    assert json.loads(sidecar.read_text())["_relativistic"] == "full"


def test_every_registered_provider_has_an_installer(registry):
    """A table listed but not installable is a promise the CLI cannot keep."""
    for table in registry.values():
        assert table.provider in {"pseudodojo", "sssp"}


def test_resolve_pseudos_prefers_an_explicit_root(registry, tmp_path):
    """A user who names a directory means that directory."""
    _pretend_installed(registry["pseudodojo-pbesol-efficiency-sr"])
    elsewhere = tmp_path / "mine"
    elsewhere.mkdir()

    assert installer.resolve_pseudos(elsewhere) == ()


def test_resolve_pseudos_reads_the_installed_tables(registry):
    _pretend_installed(registry["pseudodojo-pbesol-efficiency-sr"], ("Si.upf",))

    resolved = installer.resolve_pseudos()

    assert [m.filename for m in resolved] == ["Si.upf"]


def test_resolve_pseudos_refuses_to_proceed_when_a_run_needs_them(registry):
    with pytest.raises(installer.NoPseudopotentials):
        installer.resolve_pseudos(required=True)


def test_resolve_pseudos_is_empty_when_a_run_does_not_need_them(registry):
    """Recommending k-points needs no pseudopotentials, so it must not demand any."""
    assert installer.resolve_pseudos(required=False) == ()
