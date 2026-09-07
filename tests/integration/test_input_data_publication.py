from __future__ import annotations

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
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
    KPointSelection,
    ModelSpec,
    Provenance,
    PseudoCutoffs,
)
from goldilocks_core.ml.model_registry import load_default_qrf_config
from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.registry import load_tables
from goldilocks_core.publication import Publisher


def test_service_publication_preserves_scientific_content_and_zip_parity(
    tmp_path: Path,
) -> None:
    request = _explicit_request(tmp_path)
    pseudo_bytes = Path(request.draft.pseudo_metadata[0].filepath).read_bytes()
    directory = tmp_path / "ready"
    archive_path = tmp_path / "ready.zip"
    with Service() as service:
        result = service.compute(request, output=DirectoryOutput(directory))
        with pytest.raises(ValueError, match="does not contain DFT Input Data"):
            service.compute(
                ComputeRequest(request.draft, PresetSelection("recommend")),
                output=DirectoryOutput(tmp_path / "recommendation"),
            )

    input_data = result.records[DftInputData]
    publisher = Publisher()
    files = {item.path: item.content for item in publisher.files(input_data)}
    assert set(files) == {
        "source/original.cif",
        "structure/canonical.cif",
        "inputs/qe.in",
        "pseudo/Si.UPF",
        "licences/explicit-local-pseudopotentials.txt",
        "CITATIONS.md",
        "README.md",
        "goldilocks.json",
    }
    assert files["source/original.cif"] == request.draft.structure.content.encode()
    assert files["pseudo/Si.UPF"] == pseudo_bytes
    assert files["inputs/qe.in"].startswith(b"&CONTROL\n")
    assert (
        files["licences/explicit-local-pseudopotentials.txt"]
        == b"Fixture licence text\n"
    )
    assert b"Fixture pseudopotential citation." in files["CITATIONS.md"]
    manifest = json.loads(files["goldilocks.json"])
    assert manifest["records"]["k_points"]["grid"] == [3, 3, 3]
    assert manifest["citations"] == ["Fixture pseudopotential citation."]
    assert set(manifest["files"]) == set(files) - {"goldilocks.json"}
    for path, descriptor in manifest["files"].items():
        assert descriptor["sha256"] == hashlib.sha256(files[path]).hexdigest()
        assert descriptor["size_bytes"] == len(files[path])
    assert manifest["files"]["pseudo/Si.UPF"]["role"] == "pseudopotential"
    assert {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    } == files
    assert result.publication.path == str(directory.resolve())
    assert result.publication.files == tuple(sorted(files))
    publisher.publish(input_data, ArchiveOutput(archive_path))
    archive_bytes = publisher.archive_bytes(input_data)
    assert (
        archive_path.read_bytes()
        == archive_bytes
        == publisher.archive_bytes(input_data)
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.namelist() == sorted(files)
        assert {name: archive.read(name) for name in archive.namelist()} == files
    for output in (DirectoryOutput(directory), ArchiveOutput(archive_path)):
        with pytest.raises(FileExistsError):
            publisher.publish(input_data, output)
    assert not (tmp_path / "recommendation").exists()
    assert all(
        set(artifact) == {"path", "role"}
        for artifact in input_data.to_dict()["artifacts"]
    )
    serialized = json.dumps(input_data.to_dict())
    for private in (
        str(tmp_path),
        "filepath",
        "Fixture licence text",
        "<UPF>",
        "pseudo_info",
    ):
        assert private not in serialized


def test_explicit_pseudo_changed_after_metadata_selection_fails_before_publication(
    tmp_path: Path,
) -> None:
    request = _explicit_request(tmp_path)
    pseudo_path = Path(request.draft.pseudo_metadata[0].filepath)
    pseudo_path.write_text(
        pseudo_path.read_text(encoding="utf-8").replace("PBEsol", "LDA"),
        encoding="utf-8",
    )
    destination = tmp_path / "must-not-publish"

    with (
        Service() as service,
        pytest.raises(ValueError, match="differs from its parsed content binding"),
    ):
        service.compute(request, output=DirectoryOutput(destination))

    assert not destination.exists(follow_symlinks=False)


def test_selected_pseudo_binds_to_one_exact_same_element_candidate(
    tmp_path: Path,
) -> None:
    request = _explicit_request(tmp_path)
    candidates = []
    for identity in ("a-source", "z-source"):
        root = tmp_path / identity
        root.mkdir()
        candidate = _explicit_request(root, f"{identity}.UPF").draft.pseudo_metadata[0]
        candidates.append(
            replace(
                candidate,
                source_identifier=identity,
                pseudo_info={
                    "licence": f"{identity}-licence",
                    "licence_text": f"{identity} legal terms\n",
                    "citation": f"{identity} citation",
                },
            )
        )
    request = replace(
        request, draft=replace(request.draft, pseudo_metadata=tuple(candidates))
    )

    with Service() as service:
        result = service.compute(request)

    input_data = result.records[DftInputData]
    contents = {artifact.role: artifact.content for artifact in input_data.artifacts}
    assert contents["pseudopotential"] == Path(candidates[0].filepath).read_bytes()
    assert contents["licence"] == b"a-source legal terms\n"
    assert input_data.pseudopotential_set.licence == "a-source-licence"
    assert input_data.citations == ("a-source citation",)


def test_pseudo_root_publication_uses_explicit_legal_sidecar(tmp_path: Path) -> None:
    pseudo_root = tmp_path / "operator-pseudos"
    pseudo_root.mkdir()
    upf = pseudo_root / "Si.custom.UPF"
    request = _explicit_request(tmp_path)
    upf.write_bytes(Path(request.draft.pseudo_metadata[0].filepath).read_bytes())
    (pseudo_root / "cutoffs.json").write_text(
        json.dumps(
            {
                "Si": {
                    "filename": upf.name,
                    "md5": hashlib.md5(upf.read_bytes()).hexdigest(),
                    "functional": "PBEsol",
                    "cutoff_wfc": 30,
                    "cutoff_rho": 120,
                    "pseudopotential": "operator-library/Si.custom.UPF",
                }
            }
        ),
        encoding="utf-8",
    )
    licence_text = "Operator library redistribution terms.\n"
    licence_path = pseudo_root / "LICENSE.txt"
    licence_path.write_text(licence_text, encoding="utf-8")
    citation = "A. Scientist, Operator pseudopotential library (2026)."
    (pseudo_root / "goldilocks-pseudopotentials.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "licence": "Operator-Licence-1.0",
                "licence_file": "LICENSE.txt",
                "citation": citation,
            }
        ),
        encoding="utf-8",
    )
    request = replace(
        request,
        draft=replace(
            request.draft, pseudo_metadata=None, pseudo_root=str(pseudo_root)
        ),
    )

    with Service() as service:
        result = service.compute(request)
        licence_path.unlink()
        with pytest.raises(ValueError, match="cannot read contained.*licence_file"):
            service.compute(request)

    input_data = result.records[DftInputData]
    files = {item.path: item.content for item in Publisher().files(input_data)}
    assert input_data.pseudopotential_set.licence == "Operator-Licence-1.0"
    assert input_data.citations == (citation,)
    assert files["pseudo/Si.custom.UPF"] == upf.read_bytes()
    assert (
        files["licences/explicit-local-pseudopotentials.txt"] == licence_text.encode()
    )
    assert citation.encode() in files["CITATIONS.md"]
    serialized_result = json.dumps(result.to_dict())
    assert str(tmp_path) not in serialized_result
    assert licence_text not in serialized_result
    assert "operator-library/Si.custom.UPF" in serialized_result


def test_automatic_directory_allocation_uses_occupancy_and_is_concurrency_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    input_data = _explicit_input_data(tmp_path)
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
    assert (tmp_path / "goldilocks_out").read_text() == "occupied"
    assert (tmp_path / "goldilocks_out_2").is_symlink()


def test_write_failure_leaves_no_partial_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data = _explicit_input_data(tmp_path)
    destination = tmp_path / "failed"

    def fail_after_partial_write(root: Path, files) -> None:
        (root / files[0].path).parent.mkdir(parents=True, exist_ok=True)
        (root / files[0].path).write_bytes(files[0].content)
        assert not destination.exists()
        raise OSError("disk full")

    monkeypatch.setattr(
        publication_module, "_write_directory_path", fail_after_partial_write
    )
    with pytest.raises(OSError, match="disk full"):
        Publisher().publish(input_data, DirectoryOutput(destination))
    assert not destination.exists()
    assert not list(tmp_path.glob(".failed.*"))


@pytest.mark.parametrize("output_type", (DirectoryOutput, ArchiveOutput))
def test_install_preserves_a_raced_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_type
) -> None:
    import goldilocks_core.publication as publication_module

    input_data = _explicit_input_data(tmp_path)
    destination = tmp_path / "raced"
    rename_no_replace = publication_module._rename_no_replace

    def race(staging: Path, target: Path) -> None:
        assert not target.exists()
        target.write_bytes(b"concurrent owner")
        rename_no_replace(staging, target)

    monkeypatch.setattr(publication_module, "_rename_no_replace", race)
    with pytest.raises(FileExistsError):
        Publisher().publish(input_data, output_type(destination))
    assert destination.read_bytes() == b"concurrent owner"
    assert not list(tmp_path.glob(".raced.*"))


def _explicit_input_data(tmp_path: Path) -> DftInputData:
    with Service() as service:
        result = service.compute(_explicit_request(tmp_path))
    assert result.publication is None
    return result.records[DftInputData]


def _explicit_request(tmp_path: Path, pseudo_name: str = "Si.UPF") -> ComputeRequest:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    pseudo_path = tmp_path / pseudo_name
    pseudo_bytes = (
        b'<UPF><PP_HEADER element="Si" pseudo_type="NC" '
        b'functional="PBEsol" relativistic="scalar" z_valence="4.0" /></UPF>\n'
        + f"<!-- {pseudo_name} -->\n".encode()
    )
    pseudo_path.write_bytes(pseudo_bytes)
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InlineStructureSource(
                name="original.cif", content=structure.to(fmt="cif"), format="cif"
            ),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(
                replace(
                    parse_upf_metadata(pseudo_path),
                    filename="Si.UPF",
                    provider="fixture",
                    accuracy="efficiency",
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


def test_installed_pseudopotentials_are_snapshotted_before_publication(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "asset-sources"
    source_root.mkdir()
    pseudo_bytes = b"<UPF version='2.0.1'>installed exact fixture</UPF>\n"
    pseudo_source = source_root / "Si.UPF"
    pseudo_source.write_bytes(pseudo_bytes)
    pseudo_url = pseudo_source.as_uri()
    licence_source = source_root / "LICENSE.txt"
    licence_source.write_text("Installed exact licence\n", encoding="utf-8")
    table_manifest = source_root / "pseudo-table.json"
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
files = [
  {{role = "pseudopotentials", path = "pseudos/Si.UPF", url = "{pseudo_url}"}},
  {{role = "metadata", path = "pseudo-table.json", url = "{table_manifest.as_uri()}"}},
  {{role = "licence", path = "LICENSE.txt", url = "{licence_source.as_uri()}"}},
]
''',
        encoding="utf-8",
    )
    store = AssetStore(tmp_path / "assets")
    table = load_tables(registry)["fixture-table"]
    write_table_manifest(
        source_root,
        table,
        [
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
    )
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
    installed_root = store.root / table.asset.id / table.version
    (installed_root / "pseudos/Si.UPF").write_bytes(b"changed after compute")
    (installed_root / "LICENSE.txt").unlink()
    store.root.rename(tmp_path / "offline-assets")
    assert input_data.pseudopotential_set.id == "fixture-table"
    assert (
        input_data.pseudopotential_set.policy["preparation_fingerprint"]
        == table.asset.preparation_fingerprint
    )
    files = {item.path: item.content for item in Publisher().files(input_data)}
    assert files["pseudo/Si.UPF"] == pseudo_bytes
    assert files["licences/fixture-table.txt"] == b"Installed exact licence\n"
    assert input_data.citations == ("Installed fixture citation.",)
    assert str(store.root) not in str(input_data.to_dict())


def _stub_metallicity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "goldilocks_core.runtime.models.MetallicityModel.__call__",
        lambda self, structure: ("insulator", "model", 0.9),
    )


@pytest.mark.parametrize("hinted", [False, True])
def test_only_used_model_identities_licences_and_citations_are_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hinted: bool
) -> None:
    _stub_metallicity(monkeypatch)
    store = AssetStore(tmp_path / "model-assets")
    expected_licences: dict[str, bytes] = {}
    config = load_default_qrf_config()
    specs = (config.model_asset, config.metallicity_asset)
    used_specs = specs[1:] if hinted else specs
    for spec in specs:
        contents = {
            file.path: (
                f"Exact licence for {spec.id}@{spec.version}\n".encode()
                if file.role == "licence"
                else f"fixture {file.role}\n".encode()
            )
            for file in spec.files
        }
        _create_installed_asset(store, spec, contents)
        if spec in used_specs:
            expected_licences[
                f"licences/{spec.id.replace('/', '_')}-{spec.version}.md"
            ] = next(
                contents[file.path] for file in spec.files if file.role == "licence"
            )

    def predict(self, structure: Structure) -> KPointSelection:
        del self, structure
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

    monkeypatch.setattr("goldilocks_core.advice.kdistance.QrfBackend.__call__", predict)
    request = _explicit_request(tmp_path, "model-Si.UPF")
    if not hinted:
        request = replace(
            request,
            draft=replace(request.draft, hints=CalculationHints(pseudo_type="NC")),
        )
    with Runtime(asset_store=store) as runtime:
        with Service(runtime) as service:
            result = service.compute(request)

    input_data = result.records[DftInputData]
    files = {item.path: item.content for item in Publisher().files(input_data)}
    manifest = json.loads(files["goldilocks.json"])
    models = (
        (config.metallicity_model,)
        if hinted
        else (config.model, config.metallicity_model)
    )
    assert {
        (model["name"], model["version"], model["target"], model["revision"])
        for model in manifest["runtime"]["models"]
    } == {(model.name, model.version, model.target, model.revision) for model in models}
    assert {asset["id"]: asset for asset in manifest["runtime"]["assets"]} == {
        spec.id: {
            "id": spec.id,
            "version": spec.version,
            "preparation_fingerprint": spec.preparation_fingerprint,
        }
        for spec in used_specs
    }
    assert {
        path: files[path] for path in files if path.startswith("licences/models_")
    } == expected_licences
    assert set(input_data.citations) == {
        "Fixture pseudopotential citation.",
        *(model.citation for model in models),
    }
    assert len(input_data.citations) == len(set(input_data.citations))
    assert str(store.root) not in json.dumps(input_data.to_dict())


@pytest.mark.parametrize("missing_legal", [False, True])
def test_custom_model_revisions_and_legal_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_legal: bool
) -> None:
    _stub_metallicity(monkeypatch)

    monkeypatch.setattr(
        "goldilocks_core.advice.kindex.predict_kindex",
        lambda structure, spec: 1.0,
    )
    common = {
        "name": "shared-operator-model",
        "version": "1",
        "source": "local",
        "licence": "Operator-Model-Licence-1.0",
        "licence_text": None if missing_legal else "Operator model terms.\n",
    }
    kmesh_model = ModelSpec(
        **common,
        model_type="random_forest",
        target="k_index",
        feature_set="kmesh-features",
        location=str(tmp_path / "kmesh.joblib"),
        revision="kmesh-revision",
        citation="K-mesh model citation.",
    )
    metallicity_model = ModelSpec(
        **common,
        model_type="cgcnn",
        target="metallicity",
        feature_set="metallicity-features",
        location=str(tmp_path / "metallicity.ckpt"),
        revision="metallicity-revision",
        citation="Metallicity model citation.",
    )
    request = _explicit_request(tmp_path, "same-model-name-Si.UPF")
    request = ComputeRequest(
        replace(
            request.draft,
            hints=CalculationHints(pseudo_type="NC"),
            kmesh_model=kmesh_model,
        ),
        request.selection,
    )

    with Runtime(
        asset_store=AssetStore(tmp_path / "same-name-assets"),
        metallicity_checkpoint="metallicity.ckpt",
        metallicity_atom_init="atom-init.json",
        metallicity_model=metallicity_model,
    ) as runtime:
        with Service(runtime) as service:
            if missing_legal:
                with pytest.raises(ValueError, match="must declare non-empty licence"):
                    service.compute(request)
                return
            input_data = service.compute(request).records[DftInputData]

    assert {
        (model["target"], model["revision"]) for model in input_data.runtime.models
    } == {("k_index", "kmesh-revision"), ("metallicity", "metallicity-revision")}
    assert set(input_data.citations) == {
        "Fixture pseudopotential citation.",
        "K-mesh model citation.",
        "Metallicity model citation.",
    }
    files = {item.path: item.content for item in Publisher().files(input_data)}
    assert files["licences/custom-kmesh-model.txt"] == b"Operator model terms.\n"
    assert files["licences/custom-metallicity-model.txt"] == b"Operator model terms.\n"
    assert input_data.runtime.assets == ()
    serialized = json.dumps(input_data.to_dict())
    assert str(tmp_path) not in serialized
    assert "Operator model terms." not in serialized


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
