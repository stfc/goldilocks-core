"""Check documentation links, Python imports, CLI command vocabulary, and the
pseudopotential table spin-orbit coupling selects."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import pytest

from goldilocks_core.advisors.pseudo_selection import (
    pseudo_requirements,
    select_pseudopotential_table,
)
from goldilocks_core.assets.pseudopotentials.registry import PseudoTable, load_tables
from goldilocks_core.cli.core import build_parser
from goldilocks_core.resolution import FieldState, Unavailable

ROOT = Path(__file__).resolve().parents[2]
DOC_FILES = sorted(
    [
        ROOT / "README.md",
        *(ROOT / "docs").glob("*.md"),
        ROOT / "web" / "README.md",
        ROOT / "src" / "goldilocks_core" / "examples" / "structures" / "README.md",
    ]
)
_FENCE = re.compile(r"^```(\w+)\n(.*?)^```$", re.DOTALL | re.MULTILINE)
_GOLDILOCKS_CALL = re.compile(r"(?:uv run )?goldilocks ([\w-]+)")
_FLAG = re.compile(r"(--[\w-]+)")
_DOC_LINK = re.compile(r"\]\((?!https?://)([^)#]+(?:\.md)?)(?:#[^)]*)?\)")


def _blocks(text: str) -> list[tuple[str, str]]:
    return [(language, body) for language, body in _FENCE.findall(text)]


def _cli_vocabulary() -> tuple[frozenset[str], frozenset[str]]:
    """Command and flag names from the live argparse definitions."""
    parser = build_parser()
    flags: set[str] = set()
    for action in parser._actions:
        flags.update(action.option_strings)
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for subparser in subparsers.choices.values():
        for action in subparser._actions:
            flags.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                for leaf in action.choices.values():
                    for leaf_action in leaf._actions:
                        flags.update(leaf_action.option_strings)
    return frozenset(subparsers.choices), frozenset(flags)


def test_doc_links_resolve() -> None:
    for path in DOC_FILES:
        for match in _DOC_LINK.finditer(path.read_text()):
            target = match.group(1)
            resolved = (path.parent / target).resolve()
            assert resolved.is_file(), (
                f"{path.relative_to(ROOT)} links to missing {target}"
            )


@pytest.mark.parametrize(
    ("path", "index", "language", "body"),
    [
        pytest.param(path, index, language, body, id=f"{path.name}#{index}")
        for path in DOC_FILES
        for index, (language, body) in enumerate(_blocks(path.read_text()))
    ],
)
def test_fenced_blocks(path: Path, index: int, language: str, body: str) -> None:
    label = f"{path.relative_to(ROOT)}:{index}"
    if language == "python":
        _check_python(body, label)
    elif language == "bash":
        _check_bash(body, label)


def _check_python(body: str, label: str) -> None:
    tree = ast.parse(body, filename=label)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module == "goldilocks_core" or node.module.startswith(
            "goldilocks_core."
        ):
            module = __import__(node.module, fromlist=["__package__"])
            for alias in node.names:
                assert hasattr(module, alias.name), (
                    f"{label} imports {alias.name!r}, which "
                    f"{node.module} does not export"
                )


def _check_bash(body: str, label: str) -> None:
    commands, flags = _cli_vocabulary()
    for line in body.splitlines():
        for match in _GOLDILOCKS_CALL.finditer(line):
            command = match.group(1)
            assert command in commands, (
                f"{label} shows unknown command 'goldilocks {command}'"
            )
            for flag in _FLAG.findall(line[match.end() :]):
                assert flag in flags, f"{label} shows unknown flag {flag!r}"


def test_cli_reference_spells_out_the_task_choices() -> None:
    """docs/cli.md lists ``--task``'s choices: the ones ``run`` accepts, in
    its order."""
    subparsers = next(
        action
        for action in build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    (task,) = [
        action
        for action in subparsers.choices["run"]._actions
        if "--task" in action.option_strings
    ]
    documented = re.search(
        r"`--task \{([\w,-]+)\}`", (ROOT / "docs" / "cli.md").read_text()
    )

    assert documented is not None, "docs/cli.md does not list --task's choices"
    assert documented.group(1).split(",") == list(task.choices)


def _section(path: Path, heading: str) -> str:
    """The whitespace-normalized text of the `## heading` section of `path`."""
    text = path.read_text()
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return " ".join(text[start : end if end != -1 else len(text)].split())


def _pb_table(
    table_id: str | None, *, spin_orbit_enabled: bool
) -> FieldState[PseudoTable]:
    return select_pseudopotential_table(
        load_tables(),
        table_id=table_id,
        elements={"Pb"},
        requirements=pseudo_requirements(
            "PBEsol", spin_orbit_enabled=spin_orbit_enabled
        ),
    )


def test_pseudopotentials_page_names_the_table_spin_orbit_coupling_selects() -> None:
    """Unpinned, SOC makes selection take the fully relativistic table of the
    same provider, functional and accuracy, and a pinned scalar table is
    refused, not changed. The page states both outcomes as the code produces
    them, and its install example relies on selection instead of a pin (#179)."""
    scalar = _pb_table(None, spin_orbit_enabled=False).value
    full = _pb_table(None, spin_orbit_enabled=True).value
    assert (scalar.relativistic, full.relativistic) == ("scalar", "full")
    assert (full.provider, full.functional, full.accuracy) == (
        scalar.provider,
        scalar.functional,
        scalar.accuracy,
    )

    page = ROOT / "docs" / "pseudopotentials.md"
    choose = _section(page, "Choose a table")
    documented = re.search(
        r"fcc Pb under PBEsol goes from `([\w-]+)` to `([\w-]+)`", choose
    )
    assert documented is not None, (
        "docs/pseudopotentials.md does not name the table SOC selects for fcc Pb"
    )
    assert documented.groups() == (scalar.id, full.id)
    assert "does not change the table selection" not in choose
    pinned = _pb_table(scalar.id, spin_orbit_enabled=True)
    assert isinstance(pinned, Unavailable)
    assert pinned.reason.split("does not satisfy the request: ")[1] in choose

    (install,) = [
        body
        for language, body in _blocks(page.read_text())
        if language == "bash" and "goldilocks explain" in body
    ]
    assert f"goldilocks assets install {full.id}\n" in install
    assert "--set spin_orbit_coupling=true" in install
    assert "pseudo_table_id" not in install
