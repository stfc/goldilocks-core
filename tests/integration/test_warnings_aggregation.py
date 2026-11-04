"""#152: the top-level ``warnings`` of ``/explain``, ``/run`` and the
published ``goldilocks.json`` are the union of every record's own warnings,
for every task, each tagged with the record it came from.

``dos`` and ``vc-relax`` lost theirs: their task records (``relax``,
``dos``, the nscf step's ``nscf_*``) reached the outputs without the dict
projection the shared records got, and both collectors read dicts only.
Runs on the offline SSSP fixture table, so CI exercises it too.
"""

from __future__ import annotations

from typing import Any

import pytest
from support import mc3d_42058_silicon, sssp_fixture_table_spec, strict_json

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import bundle_files
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument

_TASKS = (
    "scf_single_point",
    "relax",
    "vc-relax",
    "dos",
    "band",
    "phonon",
    "relax-phonon",
    "vc-relax-phonon",
)

_TASK_OVERRIDES = {
    "phonon": {"is_metal": "non_metal"},
    "relax-phonon": {"is_metal": "non_metal", "use_vdw": True},
    "vc-relax-phonon": {"is_metal": "non_metal"},
}
"""The request of each phonon task on this Si cell: is_metal=non_metal, which
puts its first step on fixed occupations, as a phonon task needs for a
composition that is not all-metallic unless the user confirms a metal, and
DFT-D3 for relax-phonon, whose phonon record otherwise carries no notice."""

_TASK_RECORD_WARNINGS = {
    "dos": ("nscf_parallelisation", "parallelisation.npool_load_imbalance"),
    "band": ("bands_parallelisation", "parallelisation.npool_load_imbalance"),
    "phonon": ("phonon", "phonon.relax_first"),
    "relax-phonon": ("phonon", "phonon.d3_two_body"),
    "vc-relax-phonon": ("phonon", "phonon.vc_relax_input_cell"),
}
"""A task record that warns on this Si cell, by task, and one code it
carries: the nscf or bands step's npool notice, which #152 lost for the nscf
step, and the ph step's phonon record, which carries the phonon task's
relax-first notice, relax-phonon's two-body D3 notice and vc-relax-phonon's
input-cell notice. Its lists must carry it, so these cases fail instead of
passing on the shared records alone if the notice goes. The relax record
never warns, so relax and vc-relax have no such record to check."""


@pytest.fixture
def silicon_fixture_table(tmp_path, monkeypatch) -> None:
    """The offline Si table, installed into this test's isolated asset root
    (``conftest.isolated_default_asset_root``) as the only table."""
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources")
    AssetStore().install(spec, sssp_preparer(registry_table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {registry_table.id: registry_table},
    )


def _record_warnings(records: dict[str, Any]) -> list[dict[str, Any]]:
    """Every warning inside a published records object, tagged with its
    record, in record-name order: what the top-level list must equal."""
    return [
        {**warning, "record": name}
        for name, record in sorted(records.items())
        if record["status"] == "resolved" and isinstance(record["value"], dict)
        for warning in record["value"].get("warnings", ())
    ]


@pytest.mark.parametrize("task", _TASKS)
def test_top_level_warnings_are_the_union_of_every_record_s(
    silicon_fixture_table, task
) -> None:
    document = ComputeRequestDocument(
        structure_content=mc3d_42058_silicon().to(fmt="cif"),
        hpc="scarf",
        task=task,
        overrides=_TASK_OVERRIDES.get(task, {}),
    )

    explained = _handlers.explain(document)
    summary, bundle_input = _handlers.run(document)
    published = {file["path"]: file["content"] for file in bundle_files(bundle_input)}
    manifest = strict_json(published["goldilocks.json"])

    for output in (explained, summary, manifest):
        assert output["warnings"] == _record_warnings(output["records"])
    assert explained["warnings"] == summary["warnings"] == manifest["warnings"]
    assert "job.walltime_defaulted" in {
        warning["code"] for warning in explained["warnings"]
    }
    task_record = _TASK_RECORD_WARNINGS.get(task)
    if task_record is not None:
        for output in (explained, summary, manifest):
            assert task_record in {
                (warning["record"], warning["code"]) for warning in output["warnings"]
            }
