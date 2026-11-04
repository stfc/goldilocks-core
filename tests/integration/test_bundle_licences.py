"""#157: a bundle that ships pseudopotentials ships their table's licence.

Every published bundle -- CLI ``-o``, the HTTP ``/run`` archive, the
Workbench download -- that contains a ``pseudopotential`` artifact also
contains ``licences/<table-id>.txt``: byte for byte the installed table's
``LICENSE.txt`` (SSSP's upstream licence file, which names each family's
licence and references, or the importer's CC BY 4.0 notice for PseudoDojo),
listed in ``goldilocks.json``'s ``files`` with role ``licence`` and named by
``CITATIONS.md``. A port of v1's ``test_input_data_publication.py``
assertion, for scf, dos, band, relax and relax-phonon, published as a
directory and as an archive, on offline SSSP- and PseudoDojo-shaped tables.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from support import (
    dojo_fixture_table_spec,
    mc3d_42058_silicon,
    run_cli,
    sssp_fixture_table_spec,
    strict_json,
    write_registry,
)

from goldilocks_core.assets.pseudopotentials.importers import (
    pseudodojo_preparer,
    sssp_preparer,
)
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import ArchiveOutput, DirectoryOutput, publish
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument

pytestmark = pytest.mark.integration

_TABLES = {
    "sssp": (sssp_fixture_table_spec, sssp_preparer, b"SSSP fixture licence\n"),
    "pseudodojo": (
        dojo_fixture_table_spec,
        pseudodojo_preparer,
        b"Attribution 4.0 International licence (CC BY 4.0)",
    ),
}


@pytest.fixture(params=sorted(_TABLES))
def installed_licence(request, tmp_path, monkeypatch) -> tuple[str, bytes]:
    """One offline Si table, installed into the test's asset root and the
    only table selection can pick: its registry id and the bytes of its
    installed ``LICENSE.txt``, which carry the provider's licence text."""
    build_spec, preparer, licence_text = _TABLES[request.param]
    spec, table = build_spec(tmp_path / "sources")
    installed = AssetStore().install(spec, preparer(table))
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {table.id: table},
    )
    licence = installed.read_bytes("LICENSE.txt")
    assert licence_text in licence
    return table.id, licence


def _directory_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != ".complete"
    }


def _archive_files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _assert_ships_licence(
    files: dict[str, bytes], table_id: str, licence: bytes
) -> None:
    path = f"licences/{table_id}.txt"
    manifest = strict_json(files["goldilocks.json"])
    roles = {name: entry["role"] for name, entry in manifest["files"].items()}
    assert "pseudopotential" in roles.values()
    assert [name for name, role in roles.items() if role == "licence"] == [path]
    assert files[path] == licence
    assert manifest["files"][path] == {
        "role": "licence",
        "sha256": hashlib.sha256(licence).hexdigest(),
        "size_bytes": len(licence),
    }
    assert f"\n- `{path}`\n" in files["CITATIONS.md"].decode("utf-8")
    assert f"\n- `{path}`\n" in files["README.md"].decode("utf-8")


_OVERRIDES = {"relax-phonon": {"is_metal": "non_metal"}}
"""The request of a task that needs one for Si: is_metal=non_metal, which puts
the first step on fixed occupations, as a phonon task needs for a composition
that is not all-metallic unless the user confirms a metal."""


@pytest.mark.parametrize(
    "task", ["scf_single_point", "dos", "band", "relax", "relax-phonon"]
)
def test_every_published_bundle_ships_its_table_licence(
    installed_licence, task, tmp_path
) -> None:
    table_id, licence = installed_licence
    document = ComputeRequestDocument(
        structure_content=mc3d_42058_silicon().to(fmt="cif"),
        hpc="scarf",
        task=task,
        overrides=_OVERRIDES.get(task, {}),
    )

    summary, bundle_input = _handlers.run(document)
    publish(bundle_input, DirectoryOutput(tmp_path / "bundle"))
    publish(bundle_input, ArchiveOutput(tmp_path / "bundle.zip"))

    assert f"licences/{table_id}.txt" in summary["files"]
    for files in (
        _directory_files(tmp_path / "bundle"),
        _archive_files(tmp_path / "bundle.zip"),
    ):
        _assert_ships_licence(files, table_id, licence)


def test_the_cli_publishes_the_licence_beside_the_pseudopotentials(
    tmp_path, monkeypatch
) -> None:
    """The issue's reproduction: ``goldilocks run -o`` wrote ``pseudo/``
    and no licence file."""
    spec, table = sssp_fixture_table_spec(tmp_path / "sources")
    installed = AssetStore().install(spec, sssp_preparer(table))
    registry = tmp_path / "registry.toml"
    write_registry(registry, table)
    monkeypatch.setenv("GOLDILOCKS_PSEUDO_REGISTRY", str(registry))
    structure = tmp_path / "Si.cif"
    mc3d_42058_silicon().to(filename=str(structure))

    completed = run_cli(
        "run", str(structure), "--hpc", "scarf", "-o", str(tmp_path / "si-run")
    )

    assert completed.returncode == 0, completed.stderr
    _assert_ships_licence(
        _directory_files(tmp_path / "si-run"),
        table.id,
        installed.read_bytes("LICENSE.txt"),
    )
