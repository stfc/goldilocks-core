"""Cold imports do not load optional transports or heavy model dependencies."""

from __future__ import annotations

import subprocess
import sys


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
