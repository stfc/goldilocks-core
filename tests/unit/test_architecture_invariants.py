"""Architecture invariant gates.

These enforce the shapes the contracts-dissolution and boundary-typing
refactors established, so they cannot erode one line at a time:

- no ``to_dict`` ceremony: stage currency is dict documents, serialization
  has one policy and two serializers;
- no generic bucket packages (``utils``, ``helpers``, ``processing``);
- import discipline: code imports from the module that defines a name, never
  from the root package or a package ``__init__`` (library users may import
  the root; tests may simulate library users);
- the root surface is capped: extending ``goldilocks_core.__all__`` is a
  design decision, not an accident;
- lazy boundaries: importing ``goldilocks_core`` stays cheap and never pulls
  in optional transports or heavy ML dependencies.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import goldilocks_core

SRC = Path(goldilocks_core.__file__).resolve().parent
REPO = SRC.parent
TESTS = REPO / "tests"
LAZY_FORBIDDEN = ("fastapi", "uvicorn", "mcp", "torch", "matminer", "dscribe")
_BUCKETS = frozenset({"utils", "helpers", "common", "processing", "shared", "misc"})


def test_no_to_dict_ceremony() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        offenders.extend(
            str(path.relative_to(REPO))
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "to_dict"
        )
    assert not offenders, (
        f"to_dict ceremony reintroduced in {offenders}; serialization has one "
        "policy and two serializers (to_jsonable, to_portable)"
    )


def test_no_generic_bucket_modules() -> None:
    offenders = [
        str(path.relative_to(REPO))
        for path in sorted(SRC.rglob("*.py"))
        if path.stem in _BUCKETS
    ] + [
        str(path.relative_to(REPO))
        for path in sorted(SRC.rglob("*"))
        if path.is_dir() and path.name in _BUCKETS and (path / "__init__.py").is_file()
    ]
    assert not offenders, f"generic bucket modules are domain smells: {offenders}"


def _is_package_init(module: str) -> bool:
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        return False
    return Path(spec.origin).name == "__init__.py"


def test_import_discipline() -> None:
    """Import from the module that defines a name, never a package hub."""
    src_root_imports: list[str] = []
    hub_imports: list[str] = []
    for path in (*sorted(SRC.rglob("*.py")), *sorted(TESTS.rglob("*.py"))):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("goldilocks_core"):
                continue
            if _is_package_init(node.module):
                hub_imports.append(f"{path.relative_to(REPO)}: {node.module}")
            elif node.module == "goldilocks_core" and SRC in path.parents:
                src_root_imports.append(str(path.relative_to(REPO)))
    assert not src_root_imports, (
        f"src imports the root package; import from the defining module: "
        f"{sorted(set(src_root_imports))}"
    )
    assert not hub_imports, (
        f"imports from package __init__ hubs; import from the defining "
        f"module: {sorted(set(hub_imports))}"
    )


def test_root_surface_is_capped() -> None:
    assert len(goldilocks_core.__all__) <= 30, (
        "root surface is capped at 30 exports; widening it is a design "
        "decision, not an import convenience"
    )


@pytest.mark.parametrize("dependency", LAZY_FORBIDDEN)
def test_importing_the_package_is_lazy(dependency: str) -> None:
    probe = (
        "import sys, goldilocks_core;"
        f"loaded = {dependency!r} in sys.modules;"
        "assert not loaded, 'importing goldilocks_core pulled in '"
        f"+ {dependency!r}"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
