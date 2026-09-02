"""Documentation hygiene gates.

Every fenced ``python`` block in the docs must parse and import only names
the package actually exports; every ``goldilocks`` command and flag shown
must exist in the real CLI parser; every relative documentation link must
resolve. These gates catch docs rot before it ships: dead types
(``StructureInspection``), fabricated commands (``goldilocks recommend``),
and moved pages. README, quickstart, and tutorial Python blocks are also
*executed* against installed runtime assets by
``tests/integration/test_docs_executable.py``.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import pytest

from goldilocks_core.cli.core import build_parser

ROOT = Path(__file__).resolve().parents[2]
DOC_FILES = sorted(
    [ROOT / "README.md", *(ROOT / "docs").glob("*.md"), ROOT / "web" / "README.md"]
)
_FENCE = re.compile(r"^```(\w+)\n(.*?)^```$", re.DOTALL | re.MULTILINE)
_GOLDILOCKS_CALL = re.compile(r"(?:uv run )?goldilocks (\w+)")
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


def test_documentation_files_exist() -> None:
    assert (ROOT / "README.md").is_file()
    assert len(DOC_FILES) > 5


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
        command_matches = _GOLDILOCKS_CALL.findall(line)
        if not command_matches:
            continue
        for command in command_matches:
            assert command in commands, (
                f"{label} shows unknown command 'goldilocks {command}'"
            )
        for flag in _FLAG.findall(line):
            assert flag in flags, f"{label} shows unknown flag {flag!r}"
    assert not re.search(r"goldilocks (recommend|generate)\b", body), (
        f"{label} shows recommend/generate as commands; they are preset IDs"
    )
