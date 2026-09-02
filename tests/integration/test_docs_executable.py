"""Executable documentation.

The README, quickstart, and tutorial Python snippets run for real, in
document order, against installed runtime assets. This is the strong
freshness gate: renamed API surfaces or stale attribute access in the
copy-paste path fail the suite instead of the reader.

The test deliberately opts back into the real asset store (conftest isolates
the asset root for every test) and skips when the default profile is not
installed — CI provisions no assets, so the gates run where assets exist.
``pseudopotentials.md`` is excluded: its example selects a fully relativistic
table the default profile does not install; its blocks are still
parse/import-checked by ``tests/unit/test_docs_examples.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from goldilocks_core.assets.runtime import statuses
from goldilocks_core.assets.store import AssetStore, asset_root

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
# Computed at import time, before conftest's autouse fixture isolates the
# asset root: the executable-docs gates deliberately run against the real
# store and skip when it lacks the default profile.
REAL_ASSET_ROOT = asset_root()
EXEC_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs" / "quickstart.md",
    ROOT / "docs" / "tutorial.md",
)
_FENCE = re.compile(r"^```python\n(.*?)^```$", re.DOTALL | re.MULTILINE)


def _python_blocks(text: str) -> list[str]:
    return list(_FENCE.findall(text))


def _default_profile_installed() -> bool:
    store = AssetStore(REAL_ASSET_ROOT)
    return all(state == "installed" for _, _, state in statuses("default", store=store))


@pytest.fixture
def real_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _default_profile_installed():
        pytest.skip(f"default asset profile not installed at {REAL_ASSET_ROOT}")
    monkeypatch.setenv("GOLDILOCKS_ASSET_ROOT", str(REAL_ASSET_ROOT))


@pytest.mark.parametrize("path", EXEC_DOCUMENTS, ids=lambda path: path.name)
def test_document_python_blocks_run(
    path: Path,
    real_assets: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    for index, body in enumerate(_python_blocks(path.read_text())):
        exec(compile(body, f"<{path.name} block {index}>", "exec"), namespace)
