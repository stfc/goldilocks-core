#!/usr/bin/env python3
"""AST pre-commit hook: ban silent try/except and non-facade ``__init__.py``.

Scans every ``*.py`` under ``src/`` for three problems:

1. ``__init__.py`` files must be export-only facades (docstring, imports, and
   ``__all__`` at most).
2. ``try`` blocks whose handlers never ``raise`` swallow errors unless the
   enclosing function is tagged with ``@allow_swallow`` (the only opt-in).
3. ``contextlib.suppress`` hides exceptions and is banned outright.

The one real, testable entry point is :func:`check_source`; :func:`main`
walks ``src/`` and reports findings with a non-zero exit on any violation.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _has_allow_swallow(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether ``node`` carries an ``@allow_swallow`` decorator."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "allow_swallow":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "allow_swallow":
            return True
    return False


def _handler_raises(handler: ast.ExceptHandler) -> bool:
    """Return whether any statement inside ``handler`` is an ``ast.Raise``."""
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _check_no_swallow(
    tree: ast.AST,
    filename: str,
    in_allow_swallow: bool = False,
    funcname: str | None = None,
) -> list[str]:
    """Recurse and flag ``try`` handlers that swallow without an opt-in."""
    messages: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorated = in_allow_swallow or _has_allow_swallow(node)
            messages.extend(_check_no_swallow(node, filename, decorated, node.name))
        elif isinstance(node, ast.Try):
            if not in_allow_swallow and not all(
                _handler_raises(handler) for handler in node.handlers
            ):
                where = funcname or "<module>"
                messages.append(
                    f"{filename}:{node.lineno}: swallowing try/except in {where}"
                    " (no raise in handler) — tag with @allow_swallow or re-raise"
                )
            messages.extend(
                _check_no_swallow(node, filename, in_allow_swallow, funcname)
            )
        else:
            messages.extend(
                _check_no_swallow(node, filename, in_allow_swallow, funcname)
            )
    return messages


def _check_suppress(tree: ast.AST, filename: str) -> list[str]:
    """Flag any call to ``contextlib.suppress`` (or a bare ``suppress``)."""
    messages: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "suppress":
            messages.append(
                f"{filename}:{node.lineno}: contextlib.suppress hides exceptions"
            )
        elif isinstance(func, ast.Name) and func.id == "suppress":
            messages.append(
                f"{filename}:{node.lineno}: contextlib.suppress hides exceptions"
            )
    return messages


def _check_init(tree: ast.AST, filename: str) -> list[str]:
    """Flag anything but docstrings, imports, and ``__all__`` in ``__init__.py``."""
    messages: list[str] = []
    for node in tree.body:
        lineno = getattr(node, "lineno", 0)
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if (
                len(targets) == 1
                and isinstance(targets[0], ast.Name)
                and targets[0].id == "__all__"
            ):
                continue
            messages.append(
                f"{filename}:{lineno}: __init__.py must be export-only:"
                " found non-export assignment"
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            messages.append(
                f"{filename}:{lineno}: __init__.py must be export-only:"
                f" found def {node.name}"
            )
        elif isinstance(node, ast.ClassDef):
            messages.append(
                f"{filename}:{lineno}: __init__.py must be export-only:"
                f" found class {node.name}"
            )
        else:
            messages.append(
                f"{filename}:{lineno}: __init__.py must be export-only:"
                f" found {type(node).__name__}"
            )
        if getattr(node, "decorator_list", None):
            messages.append(
                f"{filename}:{lineno}: __init__.py must be export-only: found decorator"
            )
    return messages


def check_source(source: str, filename: str) -> list[str]:
    """Return violation messages for one source string (empty list = clean)."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno or 0}: syntax error: {exc.msg}"]
    messages: list[str] = []
    if filename.endswith("__init__.py"):
        messages.extend(_check_init(tree, filename))
    messages.extend(_check_no_swallow(tree, filename))
    messages.extend(_check_suppress(tree, filename))
    return messages


def main() -> int:
    """Walk ``src/`` and exit 1 if any file violates the no-swallow rules."""
    repo_root = Path(__file__).resolve().parent.parent
    violations: list[str] = []
    for path in sorted((repo_root / "src").rglob("*.py")):
        violations.extend(
            check_source(path.read_text(), str(path.relative_to(repo_root)))
        )
    for message in violations:
        print(message)
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
