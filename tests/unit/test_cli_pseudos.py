"""Tests for the ``gl pp`` commands."""

from __future__ import annotations

import io
import sys

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
    assert "https://www.pseudo-dojo.org/" in output
    assert "https://archive.materialscloud.org/" in output
    assert "1.3.0" in output


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


class _Stream(io.StringIO):
    """A stdout that answers isatty() however the test needs it to."""

    def __init__(self, tty: bool):
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_a_short_url_is_shown_whole():
    assert pseudos._elide("https://www.pseudo-dojo.org/", 38) == (
        "https://www.pseudo-dojo.org/"
    )


def test_a_long_url_keeps_the_part_that_says_where_it_points():
    """The host identifies the source; the record id is what can be elided."""
    elided = pseudos._elide(
        "https://archive.materialscloud.org/records/rcyfm-68h65", 38
    )

    assert elided == "https://archive.materialscloud.org/..."
    assert len(elided) == 38


def test_the_link_target_is_the_whole_url_not_the_elided_one(capsys):
    """Eliding is a display choice; clicking has to reach the actual record."""
    full = load_tables()["sssp-pbe-efficiency-sr"].upstream_url
    cell = pseudos._linked_cell(pseudos._elide(full, 38), full, 40, linked=True)

    assert f"\033]8;;{full}\033\\" in cell
    assert "rcyfm-68h65" not in cell.split("\033\\")[1]


def test_a_plain_cell_is_exactly_the_padded_text():
    """`gl pp available -v > file` must not collect escape sequences."""
    assert pseudos._linked_cell("sssp", "https://x.invalid/", 12, linked=False) == (
        "sssp        "
    )


def test_a_linked_cell_wraps_only_the_word():
    cell = pseudos._linked_cell("sssp", "https://x.invalid/", 12, linked=True)

    assert cell.startswith("\033]8;;https://x.invalid/\033\\sssp\033]8;;\033\\")
    assert cell.endswith(" " * 8)


def test_both_cells_occupy_the_same_visible_width():
    """Padding sits outside the link, so columns line up either way."""
    plain = pseudos._linked_cell("sssp", "https://x.invalid/", 12, linked=False)
    linked = pseudos._linked_cell("sssp", "https://x.invalid/", 12, linked=True)
    visible = linked.replace("\033]8;;https://x.invalid/\033\\", "")
    visible = visible.replace("\033]8;;\033\\", "")

    assert visible == plain
    assert len(visible) == 12


@pytest.mark.parametrize(
    ("tty", "no_color", "expected"),
    [
        (True, None, True),
        (False, None, False),
        (True, "1", False),
        (False, "1", False),
    ],
)
def test_links_are_emitted_only_to_a_terminal(monkeypatch, tty, no_color, expected):
    """Redirected output has to stay plain; NO_COLOR is the terminal opt-out."""
    monkeypatch.setattr(sys, "stdout", _Stream(tty))
    if no_color is None:
        monkeypatch.delenv("NO_COLOR", raising=False)
    else:
        monkeypatch.setenv("NO_COLOR", no_color)

    assert pseudos._hyperlinks_render() is expected


def test_the_listing_carries_no_escapes_under_capture(capsys):
    """The integration path, not just the helper: capture is not a terminal."""
    assert "\033" not in run_available(capsys, "-v")


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
