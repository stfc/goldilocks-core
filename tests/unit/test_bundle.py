from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure
from support import strict_json

from goldilocks_core.advisors.k_sampling import KSamplingHumanInput, k_sampling
from goldilocks_core.analysis.is_metal import is_metal
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.bundle import (
    ArchiveOutput,
    BundleInput,
    BundleStep,
    DirectoryOutput,
    RequestIdentity,
    archive_bytes,
    bundle_files,
    is_complete,
    publish,
)
from goldilocks_core.resolution import (
    Blocked,
    ModelEvidence,
    Provenance,
    Resolved,
    Unavailable,
)


def _artifact(path: str, content: bytes, role: str = "input") -> dict:
    return {"path": path, "role": role, "content": content}


_REQUEST = RequestIdentity(
    code="quantum_espresso",
    task="dos",
    hpc="scarf",
    core_version="0.1.1",
    overrides={"k_distance": 0.2, "steps.nscf.k_grid": (12, 12, 12)},
    structure={
        "name": "Si.cif",
        "format": "cif",
        "sha256": "5" * 64,
        "size_bytes": 812,
    },
)


def _bundle_input(**overrides) -> BundleInput:
    defaults = {
        "artifacts": (
            _artifact("source/original.cif", b"cif content", "structure_source"),
            _artifact("inputs/scf.in", b"&CONTROL\n/\n", "input"),
        ),
        "steps": (BundleStep(name="scf", files=("inputs/scf.in",)),),
        "run_instructions": "## Running it\n\nSubmit it.\n",
        "records": {
            "functional": Resolved("PBEsol", Provenance(source="heuristic")),
            "pseudo_table": Resolved(
                "pseudopotentials/sssp-fixture",
                Provenance(source="heuristic", citations=("A citation.",)),
            ),
        },
        "warnings": (),
        "request": _REQUEST,
    }
    defaults.update(overrides)
    return BundleInput(**defaults)


def test_publish_directory_preserves_content_and_is_complete(tmp_path: Path) -> None:
    bundle_input = _bundle_input()
    destination = tmp_path / "ready"

    publication = publish(bundle_input, DirectoryOutput(destination))

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    assert set(files) == {
        "source/original.cif",
        "inputs/scf.in",
        "CITATIONS.md",
        "README.md",
        "goldilocks.json",
    }
    on_disk = {
        path.relative_to(destination).as_posix(): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file() and path.name != ".complete"
    }
    assert on_disk == files
    assert publication["kind"] == "directory"
    assert publication["path"] == str(destination.resolve())
    assert set(publication["files"]) == set(files)
    assert (destination / ".complete").is_file()
    assert is_complete(destination) is True


def test_manifest_hashes_match_the_exact_bytes_written(tmp_path: Path) -> None:
    bundle_input = _bundle_input()
    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    manifest = json.loads(files["goldilocks.json"])

    assert set(manifest["files"]) == set(files) - {"goldilocks.json"}
    for path, descriptor in manifest["files"].items():
        assert descriptor["sha256"] == hashlib.sha256(files[path]).hexdigest()
        assert descriptor["size_bytes"] == len(files[path])
    assert manifest["files"]["source/original.cif"]["role"] == "structure_source"
    assert manifest["citations"] == ["A citation."]


def test_manifest_records_are_tri_state_aware(tmp_path: Path) -> None:
    bundle_input = _bundle_input(
        records={
            "functional": Resolved("PBEsol", Provenance(source="human")),
            "hubbard": Unavailable(reason="no correlated elements"),
            "vdw": Blocked(by="geometry blocked upstream"),
        }
    )

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    manifest = json.loads(files["goldilocks.json"])
    records = manifest["records"]

    assert records["functional"] == {
        "status": "resolved",
        "value": "PBEsol",
        "source": "human",
        "field_sources": None,
        "derived_from": [],
        "source_note": None,
        "model": None,
        "citations": [],
        "reason": None,
        "blocked_by": None,
    }
    assert records["hubbard"]["status"] == "unavailable"
    assert records["hubbard"]["reason"] == "no correlated elements"
    assert records["vdw"]["status"] == "blocked"
    assert records["vdw"]["blocked_by"] == "geometry blocked upstream"


_K_POINT_PAPER = (
    "Elena Patyukova et al., Automatic generation of input files with optimised "
    "k-point meshes for Quantum ESPRESSO self-consistent field single-point "
    "total energy calculations, Digital Discovery (2026), DOI 10.1039/D5DD00565E."
)


def _ml_record(value: object, model_id: str, asset: str) -> Resolved[object]:
    return Resolved(
        value,
        Provenance(
            source="ml",
            model=ModelEvidence(
                model_id=model_id,
                asset=asset,
                target_contract="goldilocks.fixture.v1",
                value=value,
                details={},
            ),
            citations=(_K_POINT_PAPER,),
        ),
    )


def test_citations_are_those_the_records_carry_each_listed_once() -> None:
    """#156: CITATIONS.md listed only the pseudopotential table's paper,
    read off the UPF metadata, while ML models chose the k-mesh and the
    occupations. Both CITATIONS.md and the manifest's ``citations`` now list
    every resolved record's citations: the table's and each model's, a paper
    two models share once."""
    bundle_input = _bundle_input(
        records={
            "pseudo_table": Resolved(
                "pseudopotentials/pseudodojo-pbesol-efficiency-sr",
                Provenance(
                    source="heuristic",
                    citations=(
                        "van Setten et al., Comput. Phys. Commun. 226, 39 (2018)",
                    ),
                ),
            ),
            "is_metal": _ml_record(
                False,
                "metallicity.is_metal.cgcnn@crystal_graph.v1",
                "models/is-metal-classifier@1",
            ),
            "k_sampling": _ml_record(
                0.2174,
                "k_points.k_distance.qrf@comp_struct_soap_lattice_metal.v1",
                "models/qrf-kpoints@QRF95",
            ),
            "hubbard": Unavailable(reason="no correlated elements"),
        }
    )

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    manifest = strict_json(files["goldilocks.json"])

    cited = [
        _K_POINT_PAPER,
        "van Setten et al., Comput. Phys. Commun. 226, 39 (2018)",
    ]
    assert manifest["citations"] == cited
    assert (
        "results.\n\n" + "".join(f"- {citation}\n" for citation in cited) + "\n"
    ) in files["CITATIONS.md"].decode("utf-8")
    assert manifest["records"]["k_sampling"]["model"]["model_id"] == (
        "k_points.k_distance.qrf@comp_struct_soap_lattice_metal.v1"
    )


_CITATIONS_INTRO = (
    "# Citations\n\n"
    "Cite the selected pseudopotential and model sources when publishing "
    "results.\n\n"
    "- A citation.\n"
)
_CITATIONS_PROVENANCE = (
    "\n## Provenance\n\n"
    "`goldilocks.json` holds:\n\n"
    "- `citations`: every citation the records carry, as `CITATIONS.md` lists "
    "them.\n"
    "- `records`: every decision behind the input files, with its source and "
    "provenance.\n"
)


def test_citations_point_at_every_shipped_licence() -> None:
    """#157: the per-family references SSSP's licence file lists (such as
    Topsakal & Wentzcovitch for the rare-earth PAWs) are not in the records'
    citations, so CITATIONS.md names each ``licence`` artifact the bundle
    ships; the manifest hashes it like any other file."""
    licence = b"SSSP fixture licence\n"
    bundle_input = _bundle_input(
        artifacts=(
            _artifact("scf.in", b"&CONTROL\n/\n"),
            _artifact("pseudo/Si.upf", b"<UPF/>\n", "pseudopotential"),
            _artifact("licences/sssp-fixture.txt", licence, "licence"),
        )
    )

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}

    assert files["CITATIONS.md"].decode("utf-8") == (
        _CITATIONS_INTRO + "\n## Licences\n\n"
        "Pseudopotentials keep their upstream licences. Each file below holds a "
        "table's licence material, with any per-family references to cite; read "
        "it before redistributing the pseudopotentials.\n\n"
        "- `licences/sssp-fixture.txt`\n" + _CITATIONS_PROVENANCE
    )
    assert strict_json(files["goldilocks.json"])["files"][
        "licences/sssp-fixture.txt"
    ] == {
        "role": "licence",
        "sha256": hashlib.sha256(licence).hexdigest(),
        "size_bytes": len(licence),
    }


def test_citations_name_no_licence_when_the_bundle_ships_none() -> None:
    files = {item["path"]: item["content"] for item in bundle_files(_bundle_input())}

    assert files["CITATIONS.md"].decode("utf-8") == (
        _CITATIONS_INTRO + _CITATIONS_PROVENANCE
    )


def test_manifest_warnings_are_the_bundle_input_s_verbatim() -> None:
    """#152: goldilocks.json carries the very list the transports return
    (``BundleInput.warnings``, from ``advice.warnings()``), each warning
    tagged with its record, not a second collection over its own records,
    which skipped every record that was not a dict."""
    warnings = (
        {
            "code": "parallelisation.npool_load_imbalance",
            "level": "info",
            "category": "parallelisation",
            "message": "npool=64 does not divide the 286 k-point/spin pairs evenly.",
            "record": "nscf_parallelisation",
        },
    )
    bundle_input = _bundle_input(warnings=warnings)

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    manifest = json.loads(files["goldilocks.json"])

    assert manifest["warnings"] == list(warnings)


def test_manifest_records_project_typed_decisions_without_host_paths() -> None:
    """#152: records reach the bundle as the advisors' typed decisions and
    the manifest projects them once: a pseudopotential record names its
    file, not the path it was read from on this machine."""
    metadata = PseudoMetadata(
        filepath="/home/someone/.local/share/goldilocks/assets/pseudos/Si.upf",
        filename="Si.upf",
        header_format="upf2",
        element="Si",
        z_valence=4.0,
        pseudo_info={"citation": "a citation"},
    )
    bundle_input = _bundle_input(
        records={
            "pseudopotentials": Resolved((metadata,), Provenance(source="heuristic"))
        }
    )

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    manifest = json.loads(files["goldilocks.json"])

    (entry,) = manifest["records"]["pseudopotentials"]["value"]
    assert (entry["filename"], entry["element"], entry["z_valence"]) == (
        "Si.upf",
        "Si",
        4.0,
    )
    assert "filepath" not in entry
    assert "pseudo_info" not in entry
    assert b"/home/someone" not in files["goldilocks.json"]


def test_manifest_is_strict_json_for_a_gamma_only_mesh() -> None:
    """A Gamma-only mesh is rung 1 of the k-mesh ladder, whose k-distance
    interval has no upper bound. goldilocks.json carries that bound as
    null and parses with a parser that rejects Infinity and NaN (#137)."""
    iron = Structure.from_spacegroup(
        "Im-3m", Lattice.cubic(2.87), ["Fe"], [[0.0, 0.0, 0.0]]
    )
    gamma_only = k_sampling(
        is_metal(iron), iron, human=KSamplingHumanInput(k_grid=(1, 1, 1))
    )
    bundle_input = _bundle_input(records={"k_sampling": gamma_only})

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    manifest = strict_json(files["goldilocks.json"])

    record = manifest["records"]["k_sampling"]
    assert record["value"]["k_index"] == 1
    assert record["value"]["k_distance_interval"] == [
        round(2 * math.pi / 2.87, 8),
        None,
    ]


def test_archive_bytes_match_directory_publication(tmp_path: Path) -> None:
    bundle_input = _bundle_input()
    directory = tmp_path / "dir-out"
    archive_path = tmp_path / "out.zip"

    publish(bundle_input, DirectoryOutput(directory))
    publish(bundle_input, ArchiveOutput(archive_path))

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    with zipfile.ZipFile(io.BytesIO(archive_path.read_bytes())) as archive:
        assert archive.namelist() == sorted(files)
        assert {name: archive.read(name) for name in archive.namelist()} == files
    assert archive_bytes(bundle_input) == archive_path.read_bytes()
    assert is_complete(archive_path) is True
    assert Path(f"{archive_path}.complete").is_file()


@pytest.mark.parametrize("output_type", [DirectoryOutput, ArchiveOutput])
def test_publish_never_overwrites_an_existing_destination(
    tmp_path, output_type
) -> None:
    bundle_input = _bundle_input()
    destination = tmp_path / "target"

    publish(bundle_input, output_type(destination))
    with pytest.raises(FileExistsError):
        publish(bundle_input, output_type(destination))


@pytest.mark.parametrize("output_type", [DirectoryOutput, ArchiveOutput])
def test_a_raced_destination_is_preserved_not_clobbered(tmp_path, output_type) -> None:
    """No check-then-act window to race in the first place: os.mkdir()/
    O_EXCL either claims the name atomically or fails outright, so
    whatever got there first survives untouched."""
    bundle_input = _bundle_input()
    destination = tmp_path / "raced"
    if output_type is DirectoryOutput:
        destination.mkdir()
        (destination / "marker").write_text("concurrent owner")
    else:
        destination.write_bytes(b"concurrent owner")

    with pytest.raises(FileExistsError):
        publish(bundle_input, output_type(destination))

    if output_type is DirectoryOutput:
        assert (destination / "marker").read_text() == "concurrent owner"
    else:
        assert destination.read_bytes() == b"concurrent owner"


def test_write_failure_leaves_no_partial_directory_and_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.bundle as bundle_module

    bundle_input = _bundle_input()
    destination = tmp_path / "failed"

    def fail(root: Path, files) -> None:
        (root / files[0]["path"]).parent.mkdir(parents=True, exist_ok=True)
        (root / files[0]["path"]).write_bytes(files[0]["content"])
        raise OSError("disk full")

    monkeypatch.setattr(bundle_module, "_write_directory_path", fail)
    with pytest.raises(OSError, match="disk full"):
        publish(bundle_input, DirectoryOutput(destination))

    assert not destination.exists()


def test_write_failure_on_archive_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.bundle as bundle_module

    bundle_input = _bundle_input()
    destination = tmp_path / "failed.zip"

    def fail(files) -> bytes:
        raise OSError("disk full")

    monkeypatch.setattr(bundle_module, "_archive_bytes", fail)
    with pytest.raises(OSError, match="disk full"):
        publish(bundle_input, ArchiveOutput(destination))

    assert not destination.exists()
    assert not Path(f"{destination}.complete").exists()


def test_a_directory_with_files_but_no_marker_is_not_complete(tmp_path: Path) -> None:
    """The consumer-side contract this protocol relies on: simulates what
    a SIGKILL mid-publish would leave behind -- real bytes on disk, no
    completion marker -- and confirms it reads as untrustworthy."""
    destination = tmp_path / "killed-mid-write"
    destination.mkdir()
    (destination / "inputs").mkdir()
    (destination / "inputs" / "scf.in").write_text("&CONTROL\n/\n")

    assert is_complete(destination) is False


def test_missing_target_is_not_complete(tmp_path: Path) -> None:
    assert is_complete(tmp_path / "does-not-exist") is False
    assert is_complete(tmp_path / "does-not-exist.zip") is False


@pytest.mark.parametrize(
    "unsafe_path", ["/abs/path", "a/../b", "a\\b", "a:b", "", "./x"]
)
def test_unsafe_artifact_paths_are_rejected(unsafe_path: str) -> None:
    bundle_input = _bundle_input(artifacts=(_artifact(unsafe_path, b"x"),))

    with pytest.raises(ValueError, match="unsafe"):
        bundle_files(bundle_input)


def test_duplicate_artifact_paths_are_rejected() -> None:
    bundle_input = _bundle_input(
        artifacts=(
            _artifact("inputs/scf.in", b"a"),
            _artifact("inputs/scf.in", b"b"),
        )
    )

    with pytest.raises(ValueError, match="duplicate"):
        bundle_files(bundle_input)


def test_readme_lists_every_artifact_path_without_naming_a_specific_code() -> None:
    bundle_input = _bundle_input()

    files = {item["path"]: item["content"] for item in bundle_files(bundle_input)}
    readme = files["README.md"].decode("utf-8")

    assert "inputs/scf.in" in readme
    assert "source/original.cif" in readme
    assert readme.endswith("\n## Running it\n\nSubmit it.\n")
    assert "pw.x" not in readme
    assert "quantum" not in readme.lower()


def test_readme_lists_the_inputs_in_run_order_then_each_role() -> None:
    """#222: README.md listed every path alphabetically, so a dos bundle read
    dos.in, licences/..., nscf.in, pseudo/..., scf.in, submit.sh. The inputs
    now come in the order their steps run, then the submission script, the
    pseudopotentials, the licences and any other file, each by path, and the
    manifest names the steps."""
    artifacts = tuple(
        _artifact(path, b"x", role)
        for path, role in (
            ("dos.in", "input"),
            ("licences/table.txt", "licence"),
            ("nscf.in", "input"),
            ("pseudo/Si.upf", "pseudopotential"),
            ("scf.in", "input"),
            ("source/original.cif", "structure_source"),
            ("submit.sh", "submission_script"),
        )
    )
    steps = tuple(
        BundleStep(name=name, files=(f"{name}.in",)) for name in ("scf", "nscf", "dos")
    )

    files = {
        item["path"]: item["content"]
        for item in bundle_files(_bundle_input(artifacts=artifacts, steps=steps))
    }
    readme = files["README.md"].decode("utf-8")

    assert re.findall(r"^- `([^`]+)`$", readme, flags=re.MULTILINE) == [
        "scf.in",
        "nscf.in",
        "dos.in",
        "submit.sh",
        "pseudo/Si.upf",
        "licences/table.txt",
        "source/original.cif",
    ]
    assert strict_json(files["goldilocks.json"])["steps"] == [
        {"name": "scf", "files": ["scf.in"]},
        {"name": "nscf", "files": ["nscf.in"]},
        {"name": "dos", "files": ["dos.in"]},
    ]


def test_manifest_records_the_request_the_bundle_answers() -> None:
    """#176: goldilocks.json held records, warnings, citations and file
    hashes, but not the code, task, HPC profile, engine version, overrides or
    input structure, so no bundle could be traced back to its request. Its
    ``request`` block now holds them as given, the overrides verbatim with
    their step prefixes; the manifest layout is schema_version 3, which adds
    the steps (#222)."""
    files = {item["path"]: item["content"] for item in bundle_files(_bundle_input())}
    manifest = strict_json(files["goldilocks.json"])

    assert manifest["schema_version"] == 3
    assert manifest["request"] == {
        "code": "quantum_espresso",
        "task": "dos",
        "hpc": "scarf",
        "core_version": "0.1.1",
        "overrides": {"k_distance": 0.2, "steps.nscf.k_grid": [12, 12, 12]},
        "structure": {
            "name": "Si.cif",
            "format": "cif",
            "sha256": "5" * 64,
            "size_bytes": 812,
        },
    }


def test_a_bundle_cannot_be_built_without_its_request() -> None:
    with pytest.raises(TypeError, match="'request'"):
        BundleInput(artifacts=(), records={}, warnings=())


def _manifest_keys_named(text: str) -> list[str]:
    return re.findall(r"^- `(\w+)`: ", text, flags=re.MULTILINE)


def test_readme_and_citations_describe_only_keys_the_manifest_holds() -> None:
    """#176: README.md said goldilocks.json records "which code/task it
    targets" and CITATIONS.md that it records "complete provenance": fixed
    strings that nothing checked against a manifest holding neither. Both now
    describe the manifest key by key, from the keys it is written with:
    README.md every key, CITATIONS.md the two that hold citations."""
    files = {item["path"]: item["content"] for item in bundle_files(_bundle_input())}
    manifest = strict_json(files["goldilocks.json"])
    readme = files["README.md"].decode("utf-8")

    assert (
        _manifest_keys_named(readme)
        == sorted(manifest)
        == [
            "citations",
            "files",
            "records",
            "request",
            "schema_version",
            "steps",
            "warnings",
        ]
    )
    assert readme.startswith(
        "# Goldilocks DFT Input Data\n\n`goldilocks.json` holds:\n\n"
    )
    assert (
        "- `request`: the request the bundle answers: code, task, HPC profile, "
        "the overrides as submitted, the input structure's name, format, sha256 "
        "and size, and the goldilocks-core version that answered it.\n"
    ) in readme
    assert _manifest_keys_named(files["CITATIONS.md"].decode("utf-8")) == [
        "citations",
        "records",
    ]
