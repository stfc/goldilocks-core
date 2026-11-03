"""mMACE runs outside the caller's process, so concurrent requests keep their
ML answers (#130).

mace builds its calculator under ``torch.set_default_dtype(torch.float64)``,
which is process-wide. While one request ran mMACE (an is_magnetic embedding
or an ordering ranking), a float32 model built on another request's thread
got float64 parameters and failed, and the failure looked like a missing
model: is_metal, is_magnetic and k_sampling silently answered from their
heuristics.

Local only: needs the default asset profile, whose is_magnetic asset carries
the mMACE backbone (#244), and the mace stack (docs/mmace-setup.md).
"""

from __future__ import annotations

import importlib.util
import json
import pickle
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from pymatgen.core import Lattice, Species, Structure

from goldilocks_core.examples.structures import structure
from goldilocks_core.ml import predict as predict_module
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import (
    ComputeRequestDocument,
    MagneticOrderingsRequestDocument,
)
from goldilocks_core.service import _magnetic_orderings as magnetic_orderings_module

pytestmark = [
    pytest.mark.usefixtures("real_assets"),
    pytest.mark.skipif(
        importlib.util.find_spec("mace") is None,
        reason="needs mace (docs/mmace-setup.md)",
    ),
]

_ML_RECORDS = ("is_metal", "is_magnetic", "k_sampling")
_EXPLAINED = ("Si.cif", "Fe_bcc.cif")


def _nio_candidates() -> tuple[tuple[str, Structure], ...]:
    """Rock-salt NiO's ferromagnetic guess and a compensated
    antiferromagnetic candidate (alternating Ni spins), labelled the way
    ``magnetic_config`` labels enumerated candidates: two candidates keep
    the ranking short."""
    ferromagnetic = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.17), ["Ni", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    nickel = [
        index for index, site in enumerate(ferromagnetic) if site.specie.symbol == "Ni"
    ]
    antiferromagnetic = ferromagnetic.copy()
    for position, index in enumerate(nickel):
        antiferromagnetic.replace(
            index, Species("Ni", spin=1 if position % 2 == 0 else -1)
        )
    return (("fm", ferromagnetic), ("afm-1", antiferromagnetic))


_PROBE = """
import json
import pickle
import sys

import torch

from goldilocks_core.advisors.magnetic_ordering_ml import rank_orderings
from goldilocks_core.analysis.is_magnetic import is_magnetic

with open(sys.argv[1], "rb") as candidates_file:
    candidates = pickle.load(candidates_file)
magnetism = is_magnetic(candidates[0][1])
ranking = rank_orderings(candidates)
print(json.dumps({
    "is_magnetic_source": magnetism.source,
    "winner": ranking.winner.label,
    "mace_imported": "mace" in sys.modules,
    "default_dtype": str(torch.get_default_dtype()),
}))
"""


def test_mmace_never_runs_in_the_callers_process(tmp_path: Path) -> None:
    """An is_magnetic prediction and an ordering ranking leave the calling
    process without mace and with torch's default dtype at float32."""
    candidates = tmp_path / "candidates.pickle"
    candidates.write_bytes(pickle.dumps(_nio_candidates()))

    probe = subprocess.run(
        [sys.executable, "-c", _PROBE, str(candidates)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        timeout=600,
    )

    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout.splitlines()[-1]) == {
        "is_magnetic_source": "ml",
        "winner": "afm-1",
        "mace_imported": False,
        "default_dtype": "torch.float32",
    }


def _explain(name: str) -> dict[str, Any]:
    return _handlers.explain(
        ComputeRequestDocument(structure_content=structure(name).read_text())
    )


def test_explains_during_a_ranking_match_sequential_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Workbench's Run mMACE, then a settings edit: explains run while a
    ranking does, as the first requests after startup, so every model they
    use is built during the ranking."""
    sequential = {name: _explain(name) for name in _EXPLAINED}
    assert {
        (name, key): sequential[name]["records"][key]["source"]
        for name in _EXPLAINED
        for key in _ML_RECORDS
    } == {(name, key): "ml" for name in _EXPLAINED for key in _ML_RECORDS}
    candidates = _nio_candidates()
    monkeypatch.setattr(
        magnetic_orderings_module,
        "enumerate_magnetic_orderings",
        lambda structure, moments: (candidates, None),
    )
    predict_module._model.cache_clear()

    with ThreadPoolExecutor(1 + len(_EXPLAINED)) as pool:
        ranking = pool.submit(
            _handlers.magnetic_orderings,
            MagneticOrderingsRequestDocument(
                structure_content=candidates[0][1].to(fmt="cif"),
                rank_with_mmace=True,
            ),
        )
        rounds = []
        while not ranking.done():
            rounds.append(
                dict(zip(_EXPLAINED, pool.map(_explain, _EXPLAINED), strict=True))
            )
        listing = ranking.result()

    assert [
        candidate["label"]
        for candidate in listing["candidates"]
        if candidate["is_recommended"]
    ] == ["afm-1"]
    assert rounds
    assert rounds == [sequential] * len(rounds)
