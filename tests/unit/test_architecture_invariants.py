"""Package-wide invariants: cold imports stay lazy, and CLI output names its
stream."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import goldilocks_core.cli


def test_importing_the_package_is_lazy() -> None:
    probe = """
import sys, goldilocks_core
forbidden = {'fastapi', 'uvicorn', 'mcp', 'torch', 'matminer', 'dscribe'}
loaded = forbidden.intersection(sys.modules)
assert not loaded, f'Core imported optional or heavy dependencies: {loaded}'
"""
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_every_cli_print_names_its_stream() -> None:
    """``cli.core`` points ``sys.stdout`` at stderr while a command runs
    (#183), so a ``print`` without ``file=`` would move command output off
    stdout."""
    cli_package = Path(goldilocks_core.cli.__file__).parent
    bare_prints = [
        f"{path.name}:{node.lineno}"
        for path in sorted(cli_package.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path)))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        and not any(keyword.arg == "file" for keyword in node.keywords)
    ]

    assert bare_prints == []
