"""Lint markers for the no-silent-fallback pre-commit hook.

``allow_swallow`` tags functions that are permitted to use ``try/except``
without re-raising. It is a no-op at runtime; the AST pre-commit hook reads
this decorator as the sole per-function opt-in for swallowing handlers
(no file-path allowlist — the permission travels with the function).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


def allow_swallow(fn: _F) -> _F:
    """Mark ``fn`` as permitted to swallow exceptions in its ``try/except``.

    Runtime identity — returns ``fn`` unchanged. The pre-commit hook treats
    this decorator as the only opt-in for handlers that do not re-raise.
    """
    return fn
