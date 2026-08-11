"""Tests for the ``gl pp`` commands."""

from __future__ import annotations

import pytest

from goldilocks_core.cli import core as cli_core
from goldilocks_core.cli import pseudos
from goldilocks_core.pseudo.table_registry import default_table, load_tables


@pytest.fixture(autouse=True)
def _no_installed_tables(monkeypatch, tmp_path):
    """Output must not depend on what the developer happens to have installed."""
    monkeypatch.setenv("GOLDILOCKS_CACHE", str(tmp_path / "empty-cache"))


@pytest.fixture
def never_fetches(monkeypatch):
    """Record what install() was asked for without touching the network."""
    asked: list[str] = []
    monkeypatch.setattr(
        pseudos.installer,
        "install",
        lambda table, **_kw: (asked.append(table.name), tmp_dir(table))[1],
    )
    return asked


def tmp_dir(table):
    """A destination that exists but holds nothing, so counts come out zero."""
    import pathlib
    import tempfile

    return pathlib.Path(tempfile.mkdtemp())


def run_available(capsys, *argv: str) -> str:
    """Run ``gl pp available`` with ``argv`` and return what it printed."""
    args = cli_core.build_parser().parse_args(["pp", "available", *argv])

    assert pseudos.run(args) == 0
    return capsys.readouterr().out


def run_install(capsys, *argv: str) -> tuple[int, str, str]:
    """Run ``gl pp install`` with ``argv`` and return status, stdout, stderr."""
    args = cli_core.build_parser().parse_args(["pp", "install", *argv])
    status = pseudos.run(args)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_the_brief_listing_names_every_table(capsys):
    """A name is enough to install by, so the default listing is names alone."""
    output = run_available(capsys)

    for name in load_tables():
        assert name in output


def test_the_brief_listing_omits_the_detail_columns(capsys):
    """Names already encode functional, accuracy and relativistic treatment."""
    output = run_available(capsys)

    assert "SOURCE" not in output
    assert "VERSION" not in output
    assert "ELEMENTS" not in output


def test_the_brief_listing_points_at_the_verbose_one(capsys):
    """A user cannot ask for detail they have not been told exists."""
    assert "-v" in run_available(capsys)


def test_the_verbose_listing_carries_source_and_version(capsys):
    """Neither is derivable from a name: both say what you are actually fetching."""
    output = run_available(capsys, "-v")

    assert "SOURCE" in output
    assert "VERSION" in output
    assert "materialscloud" in output
    assert "1.3.0" in output


def test_every_table_states_whether_it_is_installed(capsys):
    """Silence is ambiguous: a blank state reads as a rendering failure."""
    for argv in ((), ("-v",)):
        output = run_available(capsys, *argv)
        rows = [
            line
            for line in output.splitlines()
            if line.startswith(("pseudodojo", "sssp"))
        ]

        assert len(rows) == len(load_tables())
        assert all(row.endswith(("installed", "uninstalled")) for row in rows)


def test_the_default_is_named_rather_than_marked(capsys):
    """A symbol in a column needs a legend; the name needs nothing."""
    output = run_available(capsys)

    assert "*" not in output
    assert f"installs {default_table().name}" in output


def test_no_column_runs_into_the_next(capsys):
    """The longest name has to leave a separator before the column beside it."""
    longest = max(load_tables(), key=len)

    for argv in ((), ("-v",)):
        row = next(
            line
            for line in run_available(capsys, *argv).splitlines()
            if line.startswith(longest)
        )

        assert row[len(longest)] == " "


def test_install_defaults_to_the_one_table(capsys, never_fetches):
    status, _out, _err = run_install(capsys)

    assert status == 0
    assert never_fetches == [default_table().name]


def test_install_all_takes_every_registered_table(capsys, never_fetches):
    status, _out, _err = run_install(capsys, "--all")

    assert status == 0
    assert never_fetches == list(load_tables())


def test_install_all_quotes_the_whole_bill_first(capsys, never_fetches):
    """Naming a table is a decision about a known quantity; --all is not."""
    _status, out, _err = run_install(capsys, "--all")
    total = sum(t.transfer_bytes for t in load_tables().values())

    headline = out.splitlines()[0]
    assert f"{len(load_tables())} tables" in headline
    assert f"{total / 1e6:.0f} MB" in headline


def test_install_all_refuses_to_also_take_a_name(capsys, never_fetches):
    """The two spellings mean different things; silently ignoring one is worse."""
    status, _out, err = run_install(capsys, "--all", default_table().name)

    assert status == 2
    assert "--all" in err
    assert never_fetches == []


def test_install_rejects_an_unknown_name(capsys, never_fetches):
    status, _out, err = run_install(capsys, "sssp-2.0")

    assert status == 2
    assert "no such table" in err
    assert never_fetches == []
