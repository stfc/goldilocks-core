from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    ArchiveOutput,
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    DirectoryOutput,
    InlineStructureSource,
    PresetSelection,
    Runtime,
    Service,
)
from goldilocks_core.assets import AssetStore
from goldilocks_core.contracts import (
    DftInputData,
    GeneratedContent,
    InputArtifact,
    InstalledArtifactReference,
    KPointSelection,
    Provenance,
    PseudoCutoffs,
    PseudoMetadata,
)
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.registry import load_tables
from goldilocks_core.publication import Publisher


def test_generation_assembles_complete_dft_input_data_without_host_paths(
    tmp_path: Path,
) -> None:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    source_text = structure.to(fmt="cif")
    pseudo_bytes = b"<UPF version='2.0.1'>exact fixture</UPF>\n"
    pseudo_path = tmp_path / "Si.UPF"
    pseudo_path.write_bytes(pseudo_bytes)
    pseudo = PseudoMetadata(
        filepath=str(pseudo_path),
        filename=pseudo_path.name,
        header_format="attr",
        provider="fixture",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
        source_identifier="fixture/Si.UPF",
        pseudo_info={
            "licence": "CC-BY-4.0",
            "licence_text": "Fixture licence text\n",
            "citation": "Fixture pseudopotential citation.",
        },
    )
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InlineStructureSource(
                name="original.cif", content=source_text, format="cif"
            ),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(pseudo,),
        ),
        selection=PresetSelection("generate"),
    )

    with Service() as service:
        result = service.compute(request)

    input_data = result.records[DftInputData]
    artifacts = {artifact.path: artifact for artifact in input_data.artifacts}
    assert set(artifacts) == {
        "source/original.cif",
        "structure/canonical.cif",
        "inputs/qe.in",
        "pseudo/Si.UPF",
        "licences/explicit-local-pseudopotentials.txt",
    }
    assert isinstance(artifacts["pseudo/Si.UPF"].source, GeneratedContent)
    assert artifacts["source/original.cif"].source.content == source_text.encode()
    assert artifacts["pseudo/Si.UPF"].source.content == pseudo_bytes
    assert (
        artifacts["licences/explicit-local-pseudopotentials.txt"].source.content
        == b"Fixture licence text\n"
    )
    assert input_data.pseudopotential_set.id == "explicit-local"
    assert input_data.citations == ("Fixture pseudopotential citation.",)
    assert input_data.runtime.core_version
    assert input_data.manifest["intent"]["code"] == "quantum_espresso"
    assert input_data.manifest["hints"]["k_grid"] == [3, 3, 3]
    assert input_data.manifest["records"]["generated_files"] == [
        {"path": "inputs/qe.in", "role": "input"}
    ]
    serialized = input_data.to_dict()
    assert str(tmp_path) not in str(serialized)
    assert "filepath" not in str(serialized)

    with Service() as service:
        recommendation = service.compute(
            ComputeRequest(request.draft, PresetSelection("recommend"))
        )
    assert DftInputData not in recommendation.records


def test_publisher_builds_golden_layout_with_deterministic_zip_parity(
    tmp_path: Path,
) -> None:
    input_data, source_text, pseudo_bytes = _explicit_input_data(tmp_path)
    publisher = Publisher()

    first = publisher.files(input_data)
    second_archive = publisher.archive_bytes(input_data)
    first_archive = publisher.archive_bytes(input_data)

    files = {item.path: item.content for item in first}
    assert set(files) == {
        "source/original.cif",
        "structure/canonical.cif",
        "inputs/qe.in",
        "pseudo/Si.UPF",
        "licences/explicit-local-pseudopotentials.txt",
        "CITATIONS.md",
        "README.md",
        "goldilocks.json",
        "checksums.sha256",
    }
    assert files["source/original.cif"] == source_text.encode()
    assert files["pseudo/Si.UPF"] == pseudo_bytes
    assert files["inputs/qe.in"].startswith(b"&CONTROL\n")
    assert files["licences/explicit-local-pseudopotentials.txt"] == (
        b"Fixture licence text\n"
    )
    assert b"Fixture pseudopotential citation." in files["CITATIONS.md"]
    manifest = json.loads(files["goldilocks.json"])
    assert manifest["source"]["path"] == "source/original.cif"
    assert manifest["canonical_structure"]["path"] == "structure/canonical.cif"
    assert manifest["records"]["k_points"]["grid"] == [3, 3, 3]
    assert manifest["runtime"]["core_version"]
    assert manifest["citations"] == ["Fixture pseudopotential citation."]
    assert manifest["files"]["pseudo/Si.UPF"] == {
        "role": "pseudopotential",
        "sha256": input_data.artifacts[3].sha256,
        "size_bytes": len(pseudo_bytes),
    }
    assert first_archive == second_archive

    with zipfile.ZipFile(io.BytesIO(first_archive)) as archive:
        assert archive.namelist() == sorted(files)
        assert {name: archive.read(name) for name in archive.namelist()} == files
        assert all(
            item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist()
        )


def _explicit_input_data(tmp_path: Path) -> tuple[DftInputData, str, bytes]:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    source_text = structure.to(fmt="cif")
    pseudo_bytes = b"<UPF version='2.0.1'>exact fixture</UPF>\n"
    pseudo_path = tmp_path / "publisher-Si.UPF"
    pseudo_path.write_bytes(pseudo_bytes)
    pseudo = PseudoMetadata(
        filepath=str(pseudo_path),
        filename="Si.UPF",
        header_format="attr",
        provider="fixture",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
        source_identifier="fixture/Si.UPF",
        pseudo_info={
            "licence": "CC-BY-4.0",
            "licence_text": "Fixture licence text\n",
            "citation": "Fixture pseudopotential citation.",
        },
    )
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InlineStructureSource(
                name="original.cif", content=source_text, format="cif"
            ),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(pseudo,),
        ),
        selection=PresetSelection("generate"),
    )
    with Service() as service:
        result = service.compute(request)
    return result.records[DftInputData], source_text, pseudo_bytes


def test_publisher_rejects_unsafe_and_duplicate_logical_paths(tmp_path: Path) -> None:
    input_data, _, _ = _explicit_input_data(tmp_path)
    template = input_data.artifacts[0]
    unsafe = replace(
        template,
        path="../escaped.cif",
        source=GeneratedContent(b"escape", "unsafe-test"),
    )
    duplicate = InputArtifact(
        path=template.path,
        role="duplicate",
        sha256=template.sha256,
        size_bytes=template.size_bytes,
        source=template.source,
    )
    reserved = replace(template, path="goldilocks.json")

    cases = (
        (replace(input_data, artifacts=(unsafe,)), "Unsafe publication path"),
        (
            replace(input_data, artifacts=(*input_data.artifacts, duplicate)),
            "Duplicate publication path",
        ),
        (
            replace(input_data, artifacts=(*input_data.artifacts, reserved)),
            "Duplicate publication path",
        ),
    )
    for invalid, message in cases:
        with pytest.raises(ValueError, match=message):
            Publisher().files(invalid)


def test_publisher_atomically_writes_explicit_destinations_without_overwrite(
    tmp_path: Path,
) -> None:
    input_data, _, _ = _explicit_input_data(tmp_path)
    publisher = Publisher()
    directory = tmp_path / "ready"
    archive = tmp_path / "ready.zip"

    directory_info = publisher.publish(input_data, DirectoryOutput(directory))
    archive_info = publisher.publish(input_data, ArchiveOutput(archive))

    expected = {item.path: item.content for item in publisher.files(input_data)}
    assert directory_info.kind == "directory"
    assert directory_info.path == str(directory.resolve())
    assert directory_info.files == tuple(sorted(expected))
    assert directory_info.manifest_sha256
    assert archive_info.kind == "archive"
    assert archive_info.path == str(archive.resolve())
    assert archive_info.output_sha256
    assert {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    } == expected

    for occupied in (directory, archive):
        with pytest.raises(FileExistsError, match="already exists"):
            publisher.publish(
                input_data,
                DirectoryOutput(occupied)
                if occupied == directory
                else ArchiveOutput(occupied),
            )

    too_long = replace(
        input_data.artifacts[0],
        path=f"source/{'x' * 300}.cif",
    )
    failed_destination = tmp_path / "failed"
    with pytest.raises(OSError):
        publisher.publish(
            replace(input_data, artifacts=(too_long,)),
            DirectoryOutput(failed_destination),
        )
    assert not failed_destination.exists()
    assert not list(tmp_path.glob(".failed.*"))


def test_automatic_directory_allocation_uses_occupancy_and_is_concurrency_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    input_data, _, _ = _explicit_input_data(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "goldilocks_out").write_text("occupied", encoding="utf-8")
    (tmp_path / "goldilocks_out_1").mkdir()
    (tmp_path / "goldilocks_out_2").symlink_to("missing-target")
    publisher = Publisher()

    first = publisher.publish(input_data, DirectoryOutput())
    with ThreadPoolExecutor(max_workers=8) as pool:
        publications = tuple(
            pool.map(
                lambda _: publisher.publish(input_data, DirectoryOutput()),
                range(8),
            )
        )

    assert Path(first.path).name == "goldilocks_out_3"
    assert {Path(item.path).name for item in publications} == {
        *(f"goldilocks_out_{index}" for index in range(4, 12))
    }
    assert len({item.path for item in publications}) == 8
    assert (tmp_path / "goldilocks_out").read_text() == "occupied"
    assert (tmp_path / "goldilocks_out_2").is_symlink()


def test_service_compute_applies_output_targets_and_returns_publication_info(
    tmp_path: Path,
) -> None:
    request = _explicit_request(tmp_path, "service-Si.UPF")
    destination = tmp_path / "service-output"

    with Service() as service:
        published = service.compute(request, output=DirectoryOutput(destination))
        memory = service.compute(request, output=None)
        with pytest.raises(ValueError, match="does not contain DFT Input Data"):
            service.compute(
                ComputeRequest(request.draft, PresetSelection("recommend")),
                output=DirectoryOutput(tmp_path / "recommendation"),
            )

    assert published.publication is not None
    assert published.publication.kind == "directory"
    assert published.publication.path == str(destination.resolve())
    assert published.publication.files[-1] == "structure/canonical.cif"
    assert published.to_dict()["publication"]["manifest_sha256"]
    assert memory.publication is None
    assert not (tmp_path / "recommendation").exists()


def _explicit_request(tmp_path: Path, pseudo_name: str) -> ComputeRequest:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    pseudo_path = tmp_path / pseudo_name
    pseudo_path.write_bytes(b"<UPF version='2.0.1'>service fixture</UPF>\n")
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InlineStructureSource(
                name="original.cif", content=structure.to(fmt="cif"), format="cif"
            ),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(
                PseudoMetadata(
                    filepath=str(pseudo_path),
                    filename="Si.UPF",
                    header_format="attr",
                    provider="fixture",
                    accuracy="efficiency",
                    element="Si",
                    pseudo_type="NC",
                    functional="PBEsol",
                    relativistic="scalar",
                    cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
                    source_identifier="fixture/Si.UPF",
                    pseudo_info={
                        "licence": "CC-BY-4.0",
                        "licence_text": "Fixture licence text\n",
                        "citation": "Fixture pseudopotential citation.",
                    },
                ),
            ),
        ),
        selection=PresetSelection("generate"),
    )


def test_installed_pseudopotentials_and_licence_keep_immutable_asset_identity(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "asset-sources"
    source_root.mkdir()
    pseudo_bytes = b"<UPF version='2.0.1'>installed exact fixture</UPF>\n"
    pseudo_source = source_root / "Si.UPF"
    pseudo_source.write_bytes(pseudo_bytes)
    licence_source = source_root / "LICENSE.txt"
    licence_source.write_text("Installed exact licence\n", encoding="utf-8")
    table_manifest = source_root / "pseudo-table.json"
    table_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "fixture-table",
                "version": "1",
                "provider": "sssp",
                "functional": "PBEsol",
                "accuracy": "efficiency",
                "relativistic": "scalar",
                "licence": "Fixture-Licence",
                "citation": "Installed fixture citation.",
                "entries": [
                    {
                        "element": "Si",
                        "path": "pseudos/Si.UPF",
                        "md5": hashlib.md5(pseudo_bytes).hexdigest(),
                        "header_format": "attr",
                        "pseudo_type": "NC",
                        "z_valence": 4.0,
                        "ecutwfc_ry": 30.0,
                        "ecutrho_ry": 120.0,
                        "source_identifier": "fixture/Si.UPF",
                        "frozen_4f_core": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "pseudos.toml"
    registry.write_text(
        f'''[tables.fixture-table]
provider = "sssp"
upstream_table = "fixture"
version = "1"
functional = "PBEsol"
relativistic = "scalar"
accuracy = "efficiency"
licence = "Fixture-Licence"
citation = "Installed fixture citation."
elements = ["Si"]
default = true

[[tables.fixture-table.files]]
role = "pseudopotentials"
path = "pseudos/Si.UPF"
url = "{pseudo_source.as_uri()}"

[[tables.fixture-table.files]]
role = "metadata"
path = "pseudo-table.json"
url = "{table_manifest.as_uri()}"

[[tables.fixture-table.files]]
role = "licence"
path = "LICENSE.txt"
url = "{licence_source.as_uri()}"
''',
        encoding="utf-8",
    )
    store = AssetStore(tmp_path / "assets")
    table = load_tables(registry)["fixture-table"]
    store.install(table.asset)
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    request = ComputeRequest(
        CalculationDraft(
            InlineStructureSource("Si.cif", structure.to(fmt="cif"), "cif"),
            hints=CalculationHints(k_grid=(2, 2, 2)),
            pseudo_table="fixture-table",
        ),
        PresetSelection("generate"),
    )

    with Runtime(asset_store=store, pseudo_registry_path=registry) as runtime:
        with Service(runtime) as service:
            result = service.compute(request)
    input_data = result.records[DftInputData]
    pseudo = next(
        item for item in input_data.artifacts if item.role == "pseudopotential"
    )
    licence = next(item for item in input_data.artifacts if item.role == "licence")

    assert pseudo.source == InstalledArtifactReference(
        "fixture-table", "1", "pseudos/Si.UPF"
    )
    assert licence.source == InstalledArtifactReference(
        "fixture-table", "1", "LICENSE.txt"
    )
    assert input_data.pseudopotential_set.id == "fixture-table"
    assert input_data.pseudopotential_set.policy == {
        "accuracy": "efficiency",
        "provider": "sssp",
        "relativistic": "scalar",
    }
    files = {item.path: item.content for item in Publisher(store).files(input_data)}
    assert files["pseudo/Si.UPF"] == pseudo_bytes
    assert files["licences/fixture-table.txt"] == b"Installed exact licence\n"
    assert str(store.root) not in str(input_data.to_dict())


def test_model_runtime_identities_licences_and_citations_are_published(
    tmp_path: Path,
) -> None:
    store = AssetStore(tmp_path / "model-assets")
    expected_licences: dict[str, bytes] = {}
    for spec in model_asset_specs():
        contents = {
            file.path: (
                f"Exact licence for {spec.id}@{spec.version}\n".encode()
                if file.role == "licence"
                else f"fixture {file.role}\n".encode()
            )
            for file in spec.files
        }
        _create_installed_asset(store, spec, contents)
        expected_licences[f"licences/{spec.id}-{spec.version}.md"] = next(
            contents[file.path] for file in spec.files if file.role == "licence"
        )

    class ModelKmesh:
        def __call__(self, structure: Structure) -> KPointSelection:
            del structure
            return KPointSelection(
                grid=(4, 4, 4),
                shift=(0, 0, 0),
                mesh_type="monkhorst-pack",
                provenance=Provenance(
                    source="model",
                    reason="Fixture model prediction.",
                    data_source="fixture-qrf",
                ),
            )

        def reset(self) -> None:
            pass

        def close(self) -> None:
            pass

    request = _explicit_request(tmp_path, "model-Si.UPF")
    request = ComputeRequest(
        replace(request.draft, hints=CalculationHints(pseudo_type="NC")),
        request.selection,
    )
    with Runtime(asset_store=store, kmesh_service=ModelKmesh()) as runtime:
        with Service(runtime) as service:
            result = service.compute(request)

    input_data = result.records[DftInputData]
    assert {item.id for item in input_data.runtime.assets} == {
        "qrf-kpoints",
        "metallicity-cgcnn",
    }
    assert {model["target"] for model in input_data.runtime.models} == {
        "k_distance",
        "metallicity",
    }
    licence_artifacts = {
        item.path: item
        for item in input_data.artifacts
        if item.path in expected_licences
    }
    assert set(licence_artifacts) == set(expected_licences)
    assert all(
        isinstance(item.source, InstalledArtifactReference)
        for item in licence_artifacts.values()
    )
    files = {item.path: item.content for item in Publisher(store).files(input_data)}
    assert {path: files[path] for path in expected_licences} == expected_licences
    expected_sources = {
        file.url
        for spec in model_asset_specs()
        for file in spec.files
        if file.role == "licence"
    }
    assert expected_sources.issubset(input_data.citations)
    assert str(store.root) not in str(input_data.to_dict())


def _create_installed_asset(
    store: AssetStore, spec, contents: dict[str, bytes]
) -> None:
    root = store.root / spec.id / spec.version
    root.mkdir(parents=True)
    files = []
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "id": spec.id,
                "version": spec.version,
                "preparation_fingerprint": spec.preparation_fingerprint,
                "files": files,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("target_type", [DirectoryOutput, ArchiveOutput])
def test_output_targets_reject_empty_explicit_destinations(target_type) -> None:
    with pytest.raises(ValueError, match="destination must be a non-empty path"):
        target_type("")


def test_computation_result_serializes_input_data_without_payloads_or_host_paths(
    tmp_path: Path,
) -> None:
    request = _explicit_request(tmp_path, "serialized-Si.UPF")
    with Service() as service:
        result = service.compute(request)

    document = result.to_dict()
    json.dumps(document)
    serialized = str(document)
    assert str(tmp_path) not in serialized
    assert "filepath" not in serialized
    assert document["records"]["dft_input_data"]["artifacts"][0]["source"] == {
        "kind": "generated",
        "identity": document["records"]["dft_input_data"]["artifacts"][0]["source"][
            "identity"
        ],
    }


def test_staging_creation_failure_removes_claimed_explicit_destination(
    tmp_path: Path,
) -> None:
    input_data, _, _ = _explicit_input_data(tmp_path)
    publisher = Publisher()
    for output_type in (DirectoryOutput, ArchiveOutput):
        destination = tmp_path / ("x" * 250)
        with pytest.raises(OSError):
            publisher.publish(input_data, output_type(destination))
        assert not destination.exists()
