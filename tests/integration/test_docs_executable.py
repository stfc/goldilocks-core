"""Run Python documentation examples against installed runtime assets."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.assets.runtime import statuses
from goldilocks_core.assets.store import AssetStore, asset_root

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
# Computed at import time, before conftest's autouse fixture isolates the
# asset root: the executable-docs gates deliberately run against the real
# store and skip when it lacks the default profile.
REAL_ASSET_ROOT = asset_root()
EXEC_DOCUMENTS = (
    ROOT / "src" / "goldilocks_core" / "examples" / "structures" / "README.md",
    ROOT / "docs" / "tutorial.md",
)
"""``docs/tutorial.md`` rewritten against v2's real programmatic shape
(v2 epic 9, #9, module 7b) -- ``service.advise``/``check``/``generate``/
``RunOverrides`` via ``set_overrides.build_overrides``, not v1's
``ComputeRequest``/``compute``/``Service``/preset selection. Still not
find-and-replaced onto README.md/cli.md/quickstart.md/pseudopotentials.md:
those stay in ``test_docs_examples.py``'s ``_check_python``/``_check_bash``
deferred bucket (they lean on ``--preset``/``--model*``/``--pseudo-root``
flags with no v2 equivalent yet, since ml integration is deliberately
last, v2 epic 11)."""
_FENCE = re.compile(r"^```python\n(.*?)^```$", re.DOTALL | re.MULTILINE)
SKILL_REFERENCES = ROOT / ".agents" / "skills" / "use-goldilocks" / "references"


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


@pytest.fixture
def skill_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Diamond Si, a bulk crystal. A one-atom cubic cell with a = 5.43 A
    has 5.43 A of vacuum along every lattice vector, so it would be treated
    as an isolated atom (#126), which the magnetism heuristic spin-polarizes
    as an open-shell radical (#142)."""
    monkeypatch.chdir(tmp_path)
    structure = Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.431), ["Si"], [[0.0, 0.0, 0.0]]
    )
    structure.to(filename=tmp_path / "structure.cif")


def test_skill_workflow_publishes_recommended_grid(
    real_assets: None, skill_structure: None, tmp_path: Path
) -> None:
    path = SKILL_REFERENCES / "workflows.md"
    namespace: dict[str, object] = {}
    for index, body in enumerate(_python_blocks(path.read_text())):
        exec(compile(body, f"<{path.name} block {index}>", "exec"), namespace)

    manifest = json.loads((tmp_path / "run-dir" / "goldilocks.json").read_text())
    assert manifest["records"]["composition"]["value"]["elements"] == ["Si"]
    assert manifest["records"]["k_sampling"]["value"]["mesh"] == [4, 4, 4]
    assert manifest["request"]["overrides"] == {"k_grid": [4, 4, 4]}
    assert manifest["request"]["structure"]["name"] == "structure.cif"
    assert (tmp_path / "run-dir" / "scf.in").read_text().startswith("&CONTROL\n")


def test_skill_scf_extraction_reads_selected_scientific_values(
    real_assets: None, skill_structure: None
) -> None:
    path = SKILL_REFERENCES / "qe-scf-template.md"
    namespace: dict[str, object] = {}
    for index, body in enumerate(_python_blocks(path.read_text())):
        exec(compile(body, f"<{path.name} block {index}>", "exec"), namespace)

    assert namespace["elements"] == ("Si",)
    assert namespace["ecutwfc"] > 0
    assert namespace["ecutrho"] >= namespace["ecutwfc"]
    assert all(axis > 0 for axis in namespace["grid"])
    assert Path(namespace["pseudo_by_element"]["Si"].filename).suffix.lower() == ".upf"
