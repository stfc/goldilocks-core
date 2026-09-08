"""Enforce project import surfaces and production cyclomatic complexity."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tarfile
from pathlib import Path

PACKAGE = "goldilocks_core"
ROOT = Path(__file__).resolve().parents[1]
LIMITS = {
    "cli.core": (8, 16),
    "server.http": (5, 10),
    "server.mcp": (5, 10),
    "input_data": (10, 20),
    "runtime.scf": (10, 20),
}
DEFAULT_LIMIT = (12, 24)


def _qualified(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _imports(tree: ast.AST, package: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                yield item.asname or item.name, item.name, None
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                prefix = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join((*prefix, base)).rstrip(".")
            for item in node.names:
                yield item.asname or item.name, base, item.name


def _module_scope(tree: ast.AST):
    """Include conditional exports, but not names local to functions/classes."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            yield node
        elif not isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            yield from _module_scope(node)


def analyze(sources: dict[str, str]) -> list[dict]:
    modules = {}
    for path, source in sources.items():
        parts = Path(path).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        package = name if parts[-1] == "__init__" else name.rpartition(".")[0]
        modules[name] = (path, ast.parse(source, filename=path), package)

    exports = {}
    for name, (_, tree, package) in modules.items():
        exports[name] = {
            bound: (origin, symbol)
            for node in _module_scope(tree)
            for bound, origin, symbol in _imports(node, package)
        }

    def resolve(origin, symbol):
        seen = set()
        while (origin, symbol) not in seen:
            seen.add((origin, symbol))
            target = exports.get(origin, {}).get(symbol)
            if target is None:
                break
            origin, symbol = target
        return origin, symbol

    reports = []
    for name, (path, tree, package) in modules.items():
        if path.endswith("/__init__.py") and all(
            isinstance(node, ast.Import | ast.ImportFrom)
            or (
                isinstance(node, ast.Assign)
                and all(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            for node in tree.body
        ):
            continue  # Pure package exports are resolved at each consumer.
        dependencies = set()
        for bound, origin, symbol in _imports(tree, package):
            if origin != PACKAGE and not origin.startswith(f"{PACKAGE}."):
                continue
            if symbol == "*":
                raise ValueError(
                    f"{path}: wildcard project imports conceal the interface"
                )
            candidate = f"{origin}.{symbol}" if symbol else origin
            if candidate in modules:
                # A module alias still exposes each member used through it.
                members = {
                    qualified[len(bound) + 1 :].split(".")[0]
                    for node in ast.walk(tree)
                    if (qualified := _qualified(node)).startswith(f"{bound}.")
                }
                dependencies.update(resolve(candidate, member) for member in members)
                if not members:
                    dependencies.add((candidate, "<module>"))
            else:
                dependencies.add(resolve(origin, symbol))
        origins = {origin for origin, _ in dependencies}
        short_name = name.removeprefix(f"{PACKAGE}.")
        limits = LIMITS.get(short_name, DEFAULT_LIMIT)
        reports.append(
            {
                "module": short_name,
                "origins": len(origins),
                "symbols": len(dependencies),
                "limits": limits,
                "exceeds": len(origins) > limits[0] or len(dependencies) > limits[1],
                "dependencies": sorted(
                    f"{origin}.{symbol}" for origin, symbol in dependencies
                ),
            }
        )
    return sorted(
        reports, key=lambda row: (-row["origins"], -row["symbols"], row["module"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, help="Report imports from a captured source archive."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--report", action="store_true", help="Report without enforcing ceilings."
    )
    args = parser.parse_args()
    if args.archive:
        with tarfile.open(args.archive) as archive:
            sources = {
                member.name.removeprefix("src/"): archive.extractfile(member)
                .read()
                .decode()
                for member in archive.getmembers()
                if member.isfile() and member.name.endswith(".py")
            }
    else:
        sources = {
            path.relative_to(ROOT / "src").as_posix(): path.read_text()
            for path in (ROOT / "src" / PACKAGE).rglob("*.py")
        }
    reports = analyze(sources)
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        print(" origins symbols  ceiling  module")
        for row in reports:
            if row["exceeds"] or row["module"] in LIMITS or args.report:
                marker = "FAIL" if row["exceeds"] else "pass"
                print(
                    f"{row['origins']:8} {row['symbols']:7} "
                    f"{row['limits'][0]:2}/{row['limits'][1]:<3} "
                    f"{marker} {row['module']}"
                )
    ccn_status = 0
    if not args.archive:
        ccn_status = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "C901",
                "--ignore-noqa",
                str(ROOT / "src"),
            ],
            stdout=sys.stderr if args.json else None,
            check=False,
        ).returncode
    return int(
        not args.report and (ccn_status != 0 or any(row["exceeds"] for row in reports))
    )


if __name__ == "__main__":
    raise SystemExit(main())
