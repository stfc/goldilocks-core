#!/usr/bin/env python3
"""Pre-commit entry point for the no-swallow / ``__init__``-facade AST hook.

The checkable rules live in :func:`goldilocks_core._lint.check_source` so they
are importable by tests and covered by mutation testing; this script is a thin
CLI wrapper that walks ``src/`` and reports violations.
"""

from __future__ import annotations

from pathlib import Path

from goldilocks_core._lint import check_source


def main() -> int:
    """Walk ``src/`` and exit 1 if any file violates the no-swallow rules."""
    repo_root = Path(__file__).resolve().parent.parent
    violations: list[str] = []
    for path in sorted((repo_root / "src").rglob("*.py")):
        rel = str(path.relative_to(repo_root))
        try:
            violations.extend(check_source(path.read_text(), rel))
        except SyntaxError as exc:
            violations.append(f"{rel}:{exc.lineno or 0}: syntax error: {exc.msg}")
    for message in violations:
        print(message)
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
