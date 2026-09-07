"""Run Python documentation examples against installed runtime assets."""

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
    ROOT / "docs" / "tutorial.md",
    ROOT / "src" / "goldilocks_core" / "examples" / "structures" / "README.md",
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
