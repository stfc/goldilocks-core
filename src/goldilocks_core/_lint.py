"""Lint infrastructure: the ``allow_swallow`` marker and the no-swallow checker.

``allow_swallow`` tags functions permitted to use ``try/except`` without
re-raising; it is a runtime no-op. The AST pre-commit hook
(``scripts/check_no_swallow.py``) treats it as the sole per-function opt-in for
swallowing handlers (no file-path allowlist -- the permission rides on the
decorator).

``check_source`` implements the hook's rules over an AST. It lives in the
package (not in ``scripts/``) so it is importable by tests and covered by
mutation testing; the ``scripts/`` file is a thin CLI wrapper.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


def allow_swallow(fn: _F) -> _F:
    """Mark ``fn`` as permitted to swallow exceptions in its ``try/except``.

    Runtime identity -- returns ``fn`` unchanged. The pre-commit hook treats
    this decorator as the only opt-in for handlers that do not re-raise.
    """
    return fn


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


def _check_init(tree: ast.Module, filename: str) -> list[str]:
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
    """Return violation messages for one source string (empty list = clean).

    Raises ``SyntaxError`` if ``source`` is not valid Python; file-reading
    callers (the pre-commit hook) catch and report it.
    """
    tree = ast.parse(source, filename=filename)
    messages: list[str] = []
    if filename.endswith("__init__.py"):
        messages.extend(_check_init(tree, filename))
    messages.extend(_check_no_swallow(tree, filename))
    messages.extend(_check_suppress(tree, filename))
    return messages
