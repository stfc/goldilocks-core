"""Enforces goldilocks-core-design.md:4108's invariant as a test, per v2
epic 4 (#1)'s scope checklist: "analysis/'s functions always take only
structure (+ human/llm), never code/task/hpc."

Checked as an explicit denylist ({code, task, hpc}) rather than an allowlist
of every permitted parameter name: some analysis/ facts depend on other
facts' FieldState output rather than raw structure (needs_soc.py reads
composition, per the design doc's own dependency table and its
needs_dispersion example, "读 composition + geometry") -- the invariant's own
wording forbids specific execution-context parameters, not fact-to-fact
dependencies.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import goldilocks_core.analysis

_FORBIDDEN_PARAMETERS = frozenset({"code", "task", "hpc"})


def _public_functions():
    package = goldilocks_core.analysis
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        for name, member in vars(module).items():
            if (
                inspect.isfunction(member)
                and not name.startswith("_")
                and member.__module__ == module.__name__
            ):
                yield f"{module.__name__}.{name}", member


def test_no_analysis_function_accepts_code_task_or_hpc() -> None:
    violations = [
        (qualified_name, sorted(forbidden))
        for qualified_name, function in _public_functions()
        for forbidden in [
            set(inspect.signature(function).parameters) & _FORBIDDEN_PARAMETERS
        ]
        if forbidden
    ]

    assert violations == []


def test_at_least_one_analysis_function_was_actually_checked() -> None:
    """A denylist check that silently finds nothing to check is not a
    passing test -- confirms the package walk above actually discovers the
    real fact functions."""
    checked = {name for name, _ in _public_functions()}

    assert "goldilocks_core.analysis.is_metal.is_metal" in checked
    assert "goldilocks_core.analysis.needs_soc.needs_soc" in checked
