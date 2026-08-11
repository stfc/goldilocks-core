"""Tests for the ``gl pp`` commands."""

from __future__ import annotations

import dataclasses

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


def run_delete(capsys, *argv: str) -> tuple[int, str, str]:
    """Run ``gl pp delete`` with ``argv`` and return status, stdout, stderr."""
    args = cli_core.build_parser().parse_args(["pp", "delete", *argv])
    status = pseudos.run(args)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def pretend_installed(name: str) -> tuple:
    """Put a table's files on disk the way a real install leaves them."""
    table = load_tables()[name]
    directory = pseudos.installer.install_path(table)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Si.upf").write_text("<UPF/>")
    sidecar = directory.parent / f"{directory.name}.json"
    sidecar.write_text("{}")

    reports = directory.parent / f"{table.upstream_table}_djrepo"
    if table.provider == "pseudodojo":
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "Si.djrepo").write_text("{}")

    return table, directory, sidecar, reports


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


def test_the_verbose_listing_carries_version_and_coverage(capsys):
    """Neither is derivable from a name, which is the whole point of -v."""
    output = run_available(capsys, "-v")

    assert "VERSION" in output
    assert "ELEMENTS" in output
    assert "1.3.0" in output


def test_the_verbose_listing_repeats_nothing_the_name_already_says(capsys):
    """Functional, relativistic mode and accuracy are all in the name.

    The source URL is absent too: `gl pp install` prints it before fetching.
    """
    output = run_available(capsys, "-v")

    for column in ("XC", "REL", "ACCURACY", "SOURCE"):
        assert column not in output


def test_the_verbose_listing_quotes_the_unpacked_size(capsys):
    """The compressed archive is a third of what it becomes; the disk sees
    the larger number, so that is the one to show before installing."""
    output = run_available(capsys, "-v")
    default = default_table()

    assert "ON DISK" in output
    assert f"{default.installed_bytes / 1e6:.1f} MB" in output
    assert f"{default.transfer_bytes / 1e6:.1f} MB" not in output


def test_no_listing_prints_a_url(capsys):
    """URLs made the row three times as wide as the fact it carried."""
    for argv in ((), ("-v",)):
        assert "http" not in run_available(capsys, *argv)


def table_rows(output: str) -> list[str]:
    """Return the numbered table rows, dropping header and footer."""
    return [line for line in output.splitlines() if line.strip()[:1].isdigit()]


def test_every_table_states_whether_it_is_installed(capsys):
    """Silence is ambiguous: a blank state reads as a rendering failure."""
    for argv in ((), ("-v",)):
        rows = table_rows(run_available(capsys, *argv))

        assert len(rows) == len(load_tables())
        assert all("installed" in row or "uninstalled" in row for row in rows)


def test_the_default_is_labelled_with_the_word_default(capsys):
    """A symbol needs a legend to read; the word does not."""
    for argv in ((), ("-v",)):
        output = run_available(capsys, *argv)
        labelled = [row for row in table_rows(output) if "(default)" in row]

        assert "*" not in output
        assert len(labelled) == 1
        assert default_table().name in labelled[0]


def test_the_footer_names_the_default_too(capsys):
    """Scanning a column is work; the footer answers it outright."""
    output = run_available(capsys)

    assert f"the default is {default_table().name}" in output


def test_every_table_is_numbered_in_listing_order(capsys):
    """The number is only useful if it matches the row it sits beside."""
    for argv in ((), ("-v",)):
        rows = table_rows(run_available(capsys, *argv))

        for number, (row, name) in enumerate(zip(rows, load_tables()), start=1):
            assert row.split()[0] == str(number)
            assert row.split()[1] == name


def test_no_column_runs_into_the_next(capsys):
    """The longest name has to leave a separator before the column beside it."""
    longest = max(load_tables(), key=len)

    for argv in ((), ("-v",)):
        row = next(
            line
            for line in run_available(capsys, *argv).splitlines()
            if longest in line
        )
        after = row[row.index(longest) + len(longest) :]

        assert after.startswith(" ")


def test_install_accepts_a_number_from_the_listing(capsys, never_fetches):
    """Typing a 31-character name is the thing the number exists to avoid."""
    names = list(load_tables())
    status, _out, _err = run_install(capsys, "12")

    assert status == 0
    assert never_fetches == [names[11]]


def test_install_accepts_numbers_and_names_together(capsys, never_fetches):
    names = list(load_tables())
    status, _out, _err = run_install(capsys, "2", names[4])

    assert status == 0
    assert never_fetches == [names[1], names[4]]


@pytest.mark.parametrize("token", ["0", "16", "-1", "99"])
def test_install_rejects_a_number_outside_the_listing(capsys, never_fetches, token):
    """Off-by-one on a number silently installing the wrong table would be worse."""
    status, _out, err = run_install(capsys, token)

    assert status == 2
    assert "no such table" in err
    assert never_fetches == []


def test_install_defaults_to_the_one_table(capsys, never_fetches):
    status, _out, _err = run_install(capsys)

    assert status == 0
    assert never_fetches == [default_table().name]


def test_install_all_takes_every_registered_table(capsys, never_fetches):
    status, _out, _err = run_install(capsys, "--all")

    assert status == 0
    assert never_fetches == list(load_tables())


def test_install_all_quotes_the_whole_bill_first(capsys, never_fetches):
    """Naming a table is a decision about a known quantity; --all is not.

    Both figures, because they differ by 600 MB across the whole catalogue:
    quoting only the download would understate the disk cost threefold.
    """
    _status, out, _err = run_install(capsys, "--all")
    tables = load_tables().values()
    fetched = sum(t.transfer_bytes for t in tables)
    on_disk = sum(t.installed_bytes for t in tables)

    headline = out.splitlines()[0]
    assert f"{len(load_tables())} tables" in headline
    assert f"{fetched / 1e6:.0f} MB" in headline
    assert f"{on_disk / 1e6:.0f} MB" in headline


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


def test_delete_removes_everything_the_install_left(capsys):
    """The reports and the sidecar are part of the table, not litter beside it."""
    table, directory, sidecar, reports = pretend_installed(
        "pseudodojo-pbesol-efficiency-sr"
    )

    status, out, _err = run_delete(capsys, table.name)

    assert status == 0
    assert not directory.exists()
    assert not sidecar.exists()
    assert not reports.exists()
    assert "removed" in out


def test_delete_accepts_a_number(capsys):
    table, directory, _sidecar, _reports = pretend_installed(
        "pseudodojo-pbesol-efficiency-sr"
    )

    status, _out, _err = run_delete(capsys, "1")

    assert status == 0
    assert not directory.exists()


def test_delete_says_so_when_there_was_nothing_to_remove(capsys):
    status, out, _err = run_delete(capsys, "sssp-pbe-efficiency-sr")

    assert status == 0
    assert "not installed" in out


def test_delete_rejects_an_unknown_token_before_removing_anything(capsys):
    """All-or-nothing: a half-run delete leaves the user reconstructing which half."""
    _table, directory, _sidecar, _reports = pretend_installed(
        "pseudodojo-pbesol-efficiency-sr"
    )

    status, _out, err = run_delete(capsys, "1", "nope")

    assert status == 2
    assert "no such table" in err
    assert directory.exists()


def test_delete_refuses_a_table_resolving_outside_its_root(tmp_path):
    """Nothing reaching rmtree is taken on trust; a registry can be replaced."""
    escapee = dataclasses.replace(
        load_tables()["sssp-pbe-efficiency-sr"],
        upstream_table="../../../escaped",
    )
    target = pseudos.installer.install_path(escapee)
    target.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="outside"):
        pseudos.installer.uninstall(escapee)

    assert target.exists()
