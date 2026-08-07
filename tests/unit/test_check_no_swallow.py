"""Tests for the no-swallow / ``__init__``-facade AST pre-commit hook."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "check_no_swallow.py"

_spec = importlib.util.spec_from_file_location("check_no_swallow", _MODULE_PATH)
assert _spec and _spec.loader
_MODULE = importlib.util.module_from_spec(_spec)
sys.modules["check_no_swallow"] = _MODULE
_spec.loader.exec_module(_MODULE)

check_source = _MODULE.check_source


def test_reraise_clean():
    """A handler that re-raises is not a swallow."""
    source = """
def f():
    try:
        risky()
    except ValueError:
        raise
"""
    assert check_source(source, "mod.py") == []


def test_swallow_normal_module():
    """A handler with no raise is a swallow in a normal module."""
    source = """
def f():
    try:
        risky()
    except ValueError:
        pass
"""
    assert check_source(source, "mod.py") != []


def test_swallow_allow_swallow_exempt():
    """A swallow inside an ``@allow_swallow`` function is exempt."""
    source = """
from goldilocks_core._lint import allow_swallow

@allow_swallow
def f():
    try:
        risky()
    except ValueError:
        pass
"""
    assert check_source(source, "mod.py") == []


def test_swallow_nested_transitive_exempt():
    """A swallow in a nested function inherits the outer opt-in."""
    source = """
from goldilocks_core._lint import allow_swallow

@allow_swallow
def outer():
    def inner():
        try:
            risky()
        except ValueError:
            pass
    return inner
"""
    assert check_source(source, "mod.py") == []


def test_swallow_plain_function_violation():
    """A swallow in a non-decorated function is a violation."""
    source = """
def f():
    try:
        risky()
    except ValueError:
        pass
"""
    assert check_source(source, "mod.py") != []


def test_two_handlers_one_swallows():
    """One swallowing handler among re-raising ones is still a violation."""
    source = """
def f():
    try:
        risky()
    except KeyError:
        raise
    except ValueError:
        pass
"""
    assert check_source(source, "mod.py") != []


def test_init_facade_def_violation():
    source = """
def f():
    pass
"""
    assert check_source(source, "pkg/__init__.py") != []


def test_init_facade_class_violation():
    source = """
class C:
    pass
"""
    assert check_source(source, "pkg/__init__.py") != []


def test_init_facade_clean():
    """Docstring, import, and ``__all__`` form a clean facade."""
    source = '''"""Package facade."""

from .x import y

__all__ = ["y"]
'''
    assert check_source(source, "pkg/__init__.py") == []


def test_init_facade_non_all_assign_violation():
    source = """
_x = 1
"""
    assert check_source(source, "pkg/__init__.py") != []


def test_suppress_violation():
    source = """
import contextlib

def f():
    contextlib.suppress(ValueError)
"""
    assert check_source(source, "mod.py") != []


def test_clean_normal_module():
    """A function with a re-raising try is clean in a normal module."""
    source = """
def f():
    try:
        risky()
    except ValueError as exc:
        raise RuntimeError from exc
"""
    assert check_source(source, "mod.py") == []


@pytest.mark.parametrize(
    ("source", "filename", "expected_clean"),
    [
        ("def f():\n    pass\n", "pkg/__init__.py", False),
        ("class C: pass\n", "pkg/__init__.py", False),
        ('from .x import y\n\n__all__ = ["y"]\n', "pkg/__init__.py", True),
        ("_x = 1\n", "pkg/__init__.py", False),
        (
            "def f():\n"
            "    try:\n"
            "        risky()\n"
            "    except ValueError:\n"
            "        pass\n",
            "mod.py",
            False,
        ),
        (
            "def f():\n"
            "    try:\n"
            "        risky()\n"
            "    except ValueError:\n"
            "        raise\n",
            "mod.py",
            True,
        ),
        ("contextlib.suppress(ValueError)\n", "mod.py", False),
    ],
)
def test_parametrized(source: str, filename: str, expected_clean: bool) -> None:
    got = check_source(source, filename)
    assert (got == []) is expected_clean
