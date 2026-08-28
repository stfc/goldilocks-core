from __future__ import annotations

import errno
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
    ModelSpec,
    Provenance,
    PseudoCutoffs,
    PseudoMetadata,
    PseudopotentialSelection,
    SelectionRecord,
)
from goldilocks_core.ml.model_registry import model_asset_specs
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
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
        content_sha256=hashlib.sha256(pseudo_bytes).hexdigest(),
        content_size_bytes=len(pseudo_bytes),
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


def test_explicit_pseudo_changed_after_metadata_selection_fails_before_publication(
    tmp_path: Path,
) -> None:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    pseudo_path = tmp_path / "Si.UPF"
    pseudo_path.write_text(
        '<UPF><PP_HEADER element="Si" pseudo_type="NC" '
        'functional="PBEsol" relativistic="scalar" z_valence="4.0" /></UPF>\n',
        encoding="utf-8",
    )
    pseudo = replace(
        parse_upf_metadata(pseudo_path),
        provider="fixture",
        accuracy="efficiency",
        cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
        source_identifier="fixture/Si.UPF",
        pseudo_info={
            "licence": "CC-BY-4.0",
            "licence_text": "Fixture licence text\n",
            "citation": "Fixture pseudopotential citation.",
        },
    )
    request = ComputeRequest(
        CalculationDraft(
            InlineStructureSource("Si.cif", structure.to(fmt="cif"), "cif"),
            hints=CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC"),
            pseudo_metadata=(pseudo,),
        ),
        PresetSelection("generate"),
    )
    destination = tmp_path / "must-not-publish"
    pseudo_path.write_text(
        '<UPF><PP_HEADER element="Si" pseudo_type="NC" '
        'functional="LDA" relativistic="scalar" z_valence="4.0" /></UPF>\n',
        encoding="utf-8",
    )

    with (
        Service() as service,
        pytest.raises(ValueError, match="differs from its parsed content binding"),
    ):
        service.compute(request, output=DirectoryOutput(destination))

    assert not destination.exists(follow_symlinks=False)


def test_explicit_pseudo_without_content_binding_fails_before_publication(
    tmp_path: Path,
) -> None:
    request = _explicit_request(tmp_path, "unbound-Si.UPF")
    unbound = replace(
        request.draft.pseudo_metadata[0],
        content_sha256=None,
        content_size_bytes=None,
    )
    request = replace(
        request,
        draft=replace(request.draft, pseudo_metadata=(unbound,)),
    )
    destination = tmp_path / "unbound-must-not-publish"

    with (
        Service() as service,
        pytest.raises(ValueError, match="lacks.*content binding"),
    ):
        service.compute(request, output=DirectoryOutput(destination))

    assert not destination.exists(follow_symlinks=False)


def test_selected_pseudo_binds_to_one_exact_same_element_candidate(
    tmp_path: Path,
) -> None:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    candidates = []
    for identity, payload in (
        ("a-source", b"selected UPF\n"),
        ("z-source", b"other UPF\n"),
    ):
        root = tmp_path / identity
        root.mkdir()
        path = root / "Si.UPF"
        path.write_bytes(payload)
        candidates.append(
            PseudoMetadata(
                filepath=str(path),
                filename="Si.UPF",
                header_format="attr",
                provider="fixture",
                accuracy="efficiency",
                element="Si",
                pseudo_type="NC",
                functional="PBEsol",
                relativistic="scalar",
                cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
                source_identifier=identity,
                content_sha256=hashlib.sha256(payload).hexdigest(),
                content_size_bytes=len(payload),
                pseudo_info={
                    "licence": f"{identity}-licence",
                    "licence_text": f"{identity} legal terms\n",
                    "citation": f"{identity} citation",
                },
            )
        )
    request = ComputeRequest(
        CalculationDraft(
            InlineStructureSource("Si.cif", structure.to(fmt="cif"), "cif"),
            hints=CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC"),
            pseudo_metadata=tuple(candidates),
        ),
        PresetSelection("generate"),
    )

    with Service() as service:
        result = service.compute(request)

    input_data = result.records[DftInputData]
    pseudo = next(
        artifact
        for artifact in input_data.artifacts
        if artifact.role == "pseudopotential"
    )
    licence = next(
        artifact for artifact in input_data.artifacts if artifact.role == "licence"
    )
    assert isinstance(pseudo.source, GeneratedContent)
    assert pseudo.source.identity == "a-source"
    assert pseudo.source.content == b"selected UPF\n"
    assert isinstance(licence.source, GeneratedContent)
    assert licence.source.content == b"a-source legal terms\n"
    assert input_data.pseudopotential_set.licence == "a-source-licence"
    assert input_data.citations == ("a-source citation",)


def test_selected_pseudo_rejects_ambiguous_exact_metadata_candidates(
    tmp_path: Path,
) -> None:
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    path = tmp_path / "Si.UPF"
    path.write_bytes(b"ambiguous UPF\n")
    candidate = PseudoMetadata(
        filepath=str(path),
        filename="Si.UPF",
        header_format="attr",
        provider="fixture",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(ecutwfc_ry=30, ecutrho_ry=120),
        source_identifier="same-source",
        pseudo_info={
            "licence": "first",
            "licence_text": "first legal terms\n",
            "citation": "first citation",
        },
    )
    duplicate = replace(
        candidate,
        pseudo_info={
            "licence": "second",
            "licence_text": "second legal terms\n",
            "citation": "second citation",
        },
    )
    request = ComputeRequest(
        CalculationDraft(
            InlineStructureSource("Si.cif", structure.to(fmt="cif"), "cif"),
            hints=CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC"),
            pseudo_metadata=(candidate, duplicate),
        ),
        PresetSelection("generate"),
    )

    with Service() as service, pytest.raises(ValueError, match="ambiguous.*Si"):
        service.compute(request)


def test_selected_pseudo_binding_uses_source_identity_for_same_path_candidates(
    tmp_path: Path,
) -> None:
    from goldilocks_core.input_data import _bind_selected_pseudo_metadata

    path = tmp_path / "Si.UPF"
    first = PseudoMetadata(
        filepath=str(path),
        filename="Si.UPF",
        header_format="attr",
        provider="first-source",
        element="Si",
    )
    second = replace(first, provider="second-source")
    selected = PseudopotentialSelection(
        element="Si",
        filename="Si.UPF",
        filepath=str(path),
        functional="PBEsol",
        relativistic="scalar",
        ecutwfc_ry=30,
        ecutrho_ry=120,
        provenance=Provenance(
            source="lookup",
            reason="Fixture selection.",
            data_source="first-source",
        ),
    )

    assert _bind_selected_pseudo_metadata(
        SelectionRecord((selected,)),
        (first, second),
    ) == (first,)


def test_selected_pseudo_rejects_zero_exact_metadata_candidates(
    tmp_path: Path,
) -> None:
    from goldilocks_core.input_data import _bind_selected_pseudo_metadata

    candidate_path = tmp_path / "candidate" / "Si.UPF"
    candidate = PseudoMetadata(
        filepath=str(candidate_path),
        filename="Si.UPF",
        header_format="attr",
        provider="fixture",
        element="Si",
        source_identifier="fixture-source",
    )
    selected = PseudopotentialSelection(
        element="Si",
        filename="Si.UPF",
        filepath=str(tmp_path / "other" / "Si.UPF"),
        functional="PBEsol",
        relativistic="scalar",
        ecutwfc_ry=30,
        ecutrho_ry=120,
        provenance=Provenance(
            source="lookup",
            reason="Fixture selection.",
            data_source="fixture",
        ),
    )

    with pytest.raises(ValueError, match="no exact metadata candidate.*Si"):
        _bind_selected_pseudo_metadata(
            SelectionRecord((selected,)),
            (candidate,),
        )


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
        content_sha256=hashlib.sha256(pseudo_bytes).hexdigest(),
        content_size_bytes=len(pseudo_bytes),
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


def test_pseudo_root_publication_uses_explicit_legal_sidecar(tmp_path: Path) -> None:
    pseudo_root = tmp_path / "operator-pseudos"
    pseudo_root.mkdir()
    upf = pseudo_root / "Si.custom.UPF"
    upf.write_text(
        '<UPF><PP_HEADER element="Si" pseudo_type="NC" '
        'functional="PBEsol" relativistic="scalar" '
        'z_valence="4.0" /></UPF>\n',
        encoding="utf-8",
    )
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
    (pseudo_root / "LICENSE.txt").write_text(licence_text, encoding="utf-8")
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
    structure = Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
    request = ComputeRequest(
        CalculationDraft(
            InlineStructureSource("Si.cif", structure.to(fmt="cif"), "cif"),
            hints=CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC"),
            pseudo_root=str(pseudo_root),
        ),
        PresetSelection("generate"),
    )

    with Service() as service:
        result = service.compute(request)

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


def test_publisher_rejects_control_characters_before_writing_checksums(
    tmp_path: Path,
) -> None:
    input_data, _, _ = _explicit_input_data(tmp_path)
    template = input_data.artifacts[0]
    injected = replace(
        template,
        path=(f"source/structure.cif\n{'0' * 64}  forged/entry"),
    )

    with pytest.raises(ValueError, match="Unsafe publication path"):
        Publisher().files(replace(input_data, artifacts=(injected,)))


@pytest.mark.parametrize("control", ("\r", "\x00", "\x1f", "\x7f", "\x85"))
def test_publisher_rejects_every_control_character_in_paths(
    tmp_path: Path, control: str
) -> None:
    input_data, _, _ = _explicit_input_data(tmp_path)
    artifact = replace(input_data.artifacts[0], path=f"source/a{control}b.cif")

    with pytest.raises(ValueError, match="Unsafe publication path"):
        Publisher().files(replace(input_data, artifacts=(artifact,)))


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


def test_directory_publication_uses_windows_private_path_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "windows-ready"
    calls: list[tuple[Path, Path]] = []

    def move_no_replace(source: Path, target: Path) -> None:
        calls.append((source, target))
        if target.exists(follow_symlinks=False):
            raise FileExistsError(target)
        source.rename(target)

    monkeypatch.setattr(publication_module, "_publication_platform", lambda: "windows")
    monkeypatch.setattr(
        publication_module,
        "_windows_rename_no_replace",
        move_no_replace,
    )

    publication = Publisher().publish(input_data, DirectoryOutput(destination))

    assert publication.path == str(destination)
    assert len(calls) == 1
    assert calls[0][1] == destination
    assert (destination / "goldilocks.json").is_file()
    assert not list(tmp_path.glob(".windows-ready.*"))


@pytest.mark.parametrize(
    ("platform", "implementation"),
    (("linux", "_linux_rename_no_replace"), ("darwin", "_darwin_rename_no_replace")),
)
def test_native_no_replace_dispatches_to_supported_unix_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    implementation: str,
) -> None:
    import goldilocks_core.publication as publication_module

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(publication_module, "_publication_platform", lambda: platform)
    monkeypatch.setattr(
        publication_module,
        implementation,
        lambda actual_source, actual_destination: calls.append(
            (actual_source, actual_destination)
        ),
    )

    publication_module._native_rename_no_replace(source, destination)

    assert calls == [(source, destination)]


def test_windows_native_install_uses_move_without_replace_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    calls: list[tuple[str, str, int]] = []

    class NativeMove:
        def __call__(self, source: str, destination: str, flags: int) -> int:
            calls.append((source, destination, flags))
            return 1

    class Kernel32:
        MoveFileExW = NativeMove()

    monkeypatch.setattr(
        publication_module.ctypes,
        "WinDLL",
        lambda name, use_last_error: Kernel32(),
        raising=False,
    )
    source = tmp_path / "source"
    destination = tmp_path / "destination"

    publication_module._windows_rename_no_replace(source, destination)

    assert calls == [(str(source), str(destination), 0)]


def test_windows_native_install_reports_existing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    class NativeMove:
        def __call__(self, source: str, destination: str, flags: int) -> int:
            del source, destination, flags
            return 0

    class Kernel32:
        MoveFileExW = NativeMove()

    monkeypatch.setattr(
        publication_module.ctypes,
        "WinDLL",
        lambda name, use_last_error: Kernel32(),
        raising=False,
    )
    monkeypatch.setattr(
        publication_module.ctypes,
        "get_last_error",
        lambda: 183,
        raising=False,
    )

    with pytest.raises(FileExistsError):
        publication_module._windows_rename_no_replace(
            tmp_path / "source", tmp_path / "destination"
        )


def test_macos_native_install_requests_exclusive_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    calls: list[tuple[bytes, bytes, int]] = []

    class NativeRename:
        def __call__(self, source: bytes, destination: bytes, flags: int) -> int:
            calls.append((source, destination, flags))
            return 0

    class LibC:
        renamex_np = NativeRename()

    monkeypatch.setattr(
        publication_module.ctypes,
        "CDLL",
        lambda library, use_errno: LibC(),
    )
    source = tmp_path / "source"
    destination = tmp_path / "destination"

    publication_module._darwin_rename_no_replace(source, destination)

    assert calls == [(bytes(source), bytes(destination), 0x00000004)]


def test_directory_publication_rejects_unsupported_unix_before_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "unsupported"
    monkeypatch.setattr(
        publication_module,
        "_publication_platform",
        lambda: "unsupported_unix",
    )

    with pytest.raises(OSError) as raised:
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert raised.value.errno == errno.ENOTSUP
    assert not destination.exists(follow_symlinks=False)
    assert not list(tmp_path.glob(".unsupported.*"))


def test_automatic_directory_allocation_uses_occupancy_and_is_concurrency_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    import goldilocks_core.publication as publication_module

    class AutomaticRootPath(type(Path())):
        @classmethod
        def cwd(cls):
            return cls(tmp_path)

    input_data, _, _ = _explicit_input_data(tmp_path)
    (tmp_path / "goldilocks_out").write_text("occupied", encoding="utf-8")
    (tmp_path / "goldilocks_out_1").mkdir()
    (tmp_path / "goldilocks_out_2").symlink_to("missing-target")
    monkeypatch.setattr(publication_module, "Path", AutomaticRootPath)
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


def test_directory_target_stays_absent_until_a_complete_tree_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "not-public-until-complete"
    verify_directory = publication_module._verify_directory
    verified_private_staging = False

    def observe(root: Path, files) -> None:
        nonlocal verified_private_staging
        if root != destination:
            verified_private_staging = True
            assert not destination.exists()
        verify_directory(root, files)

    monkeypatch.setattr(publication_module, "_verify_directory", observe)

    Publisher().publish(input_data, DirectoryOutput(destination))

    assert verified_private_staging
    assert (destination / "goldilocks.json").is_file()


@pytest.mark.parametrize("foreign_kind", ("file", "directory"))
def test_directory_install_never_replaces_or_removes_a_raced_foreign_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    foreign_kind: str,
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "raced-destination"
    rename_no_replace = publication_module._rename_no_replace

    def race(staging: Path, target: Path) -> None:
        assert (staging / "goldilocks.json").is_file()
        if foreign_kind == "file":
            target.write_text("foreign file", encoding="utf-8")
        else:
            target.mkdir()
            (target / "foreign.txt").write_text("foreign directory", encoding="utf-8")
        rename_no_replace(staging, target)

    monkeypatch.setattr(publication_module, "_rename_no_replace", race)

    with pytest.raises(FileExistsError, match="already exists"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    if foreign_kind == "file":
        assert destination.read_text(encoding="utf-8") == "foreign file"
    else:
        assert (destination / "foreign.txt").read_text(encoding="utf-8") == (
            "foreign directory"
        )
    assert not list(tmp_path.glob(".raced-destination.*"))


def test_automatic_directory_allocation_advances_after_no_replace_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    class AutomaticRootPath(type(Path())):
        @classmethod
        def cwd(cls):
            return cls(tmp_path)

    input_data, _, _ = _explicit_input_data(tmp_path)
    rename_no_replace = publication_module._rename_no_replace
    raced = False

    def race_once(staging: Path, target: Path) -> None:
        nonlocal raced
        assert (staging / "goldilocks.json").is_file()
        if not raced:
            raced = True
            target.mkdir()
            (target / "foreign.txt").write_text("foreign", encoding="utf-8")
        rename_no_replace(staging, target)

    monkeypatch.setattr(publication_module, "Path", AutomaticRootPath)
    monkeypatch.setattr(publication_module, "_rename_no_replace", race_once)

    publication = Publisher().publish(input_data, DirectoryOutput())

    assert Path(publication.path).name == "goldilocks_out_1"
    assert (tmp_path / "goldilocks_out" / "foreign.txt").read_text() == "foreign"
    assert (tmp_path / "goldilocks_out_1" / "goldilocks.json").is_file()


def test_preinstall_failure_removes_only_private_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "foreign-on-failure"

    def fail_before_install(root: Path, files) -> None:
        del root, files
        destination.mkdir()
        (destination / "foreign.txt").write_text("foreign", encoding="utf-8")
        raise OSError("private staging verification failed")

    monkeypatch.setattr(publication_module, "_verify_directory", fail_before_install)

    with pytest.raises(OSError, match="private staging verification failed"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert (destination / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert not list(tmp_path.glob(".foreign-on-failure.*"))


def test_preinstall_cleanup_never_removes_a_foreign_staging_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "must-stay-absent"
    displaced = tmp_path / "displaced-owned-staging"
    foreign_staging: Path | None = None

    def replace_staging_then_fail(staging: Path, target: Path) -> None:
        nonlocal foreign_staging
        del target
        staging.rename(displaced)
        staging.mkdir()
        (staging / "foreign.txt").write_text("foreign", encoding="utf-8")
        foreign_staging = staging
        raise FileExistsError("forced no-replace race")

    monkeypatch.setattr(
        publication_module,
        "_rename_no_replace",
        replace_staging_then_fail,
    )

    with pytest.raises(FileExistsError, match="already exists"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists()
    assert foreign_staging is not None
    assert (foreign_staging / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert (displaced / "goldilocks.json").is_file()


def test_directory_writes_remain_bound_to_open_staging_descriptor_after_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "descriptor-bound-directory"
    displaced = tmp_path / "displaced-descriptor-directory"
    descriptor_identity = publication_module._descriptor_identity
    foreign_staging: Path | None = None

    def replace_after_descriptor_open(descriptor: int) -> tuple[int, int]:
        nonlocal foreign_staging
        identity = descriptor_identity(descriptor)
        staging = next(tmp_path.glob(".descriptor-bound-directory.*"))
        staging.rename(displaced)
        staging.mkdir()
        (staging / "foreign.txt").write_text("foreign", encoding="utf-8")
        foreign_staging = staging
        return identity

    monkeypatch.setattr(
        publication_module,
        "_descriptor_identity",
        replace_after_descriptor_open,
    )

    with pytest.raises(OSError, match="staging changed during publication"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists()
    assert foreign_staging is not None
    assert list(foreign_staging.iterdir()) == [foreign_staging / "foreign.txt"]
    assert (foreign_staging / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert (displaced / "goldilocks.json").is_file()


def test_directory_identity_mismatch_restores_moved_foreign_staging_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "moved-replacement"
    displaced = tmp_path / "displaced-owned-publication"
    foreign_staging: Path | None = None

    def move_replacement(staging: Path, target: Path) -> None:
        nonlocal foreign_staging
        staging.rename(displaced)
        staging.mkdir()
        (staging / "foreign.txt").write_text("foreign", encoding="utf-8")
        foreign_staging = staging
        publication_module._native_rename_no_replace(staging, target)

    monkeypatch.setattr(publication_module, "_rename_no_replace", move_replacement)

    with pytest.raises(OSError, match="changed during publication"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists()
    assert foreign_staging is not None
    assert (foreign_staging / "foreign.txt").read_text(encoding="utf-8") == "foreign"
    assert (displaced / "goldilocks.json").is_file()


def test_directory_publication_quarantines_foreign_file_added_after_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "modified-after-install"
    rename_no_replace = publication_module._rename_no_replace

    def modify_after_install(staging: Path, target: Path) -> None:
        rename_no_replace(staging, target)
        (target / "foreign.txt").write_text("foreign", encoding="utf-8")

    monkeypatch.setattr(publication_module, "_rename_no_replace", modify_after_install)

    with pytest.raises(OSError, match="Completed directory descriptor write differs"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists(follow_symlinks=False)
    quarantined = list(tmp_path.glob(".modified-after-install.quarantine-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "goldilocks.json").is_file()
    assert (quarantined[0] / "foreign.txt").read_text(encoding="utf-8") == "foreign"


def test_directory_publication_quarantines_symlink_installed_by_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, pseudo_bytes = _explicit_input_data(tmp_path)
    destination = tmp_path / "symlinked-after-install"
    host_target = tmp_path / "host-secret-target"
    host_target.write_bytes(pseudo_bytes)
    rename_no_replace = publication_module._rename_no_replace

    def replace_file_after_install(staging: Path, target: Path) -> None:
        rename_no_replace(staging, target)
        published_pseudo = target / "pseudo" / "Si.UPF"
        published_pseudo.unlink()
        published_pseudo.symlink_to(host_target)

    monkeypatch.setattr(
        publication_module,
        "_rename_no_replace",
        replace_file_after_install,
    )

    with pytest.raises(OSError, match="non-regular path"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists(follow_symlinks=False)
    assert host_target.is_file()
    assert not host_target.is_symlink()
    assert host_target.read_bytes() == pseudo_bytes


def test_directory_publication_quarantines_replacement_after_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "replaced-after-install"
    displaced = tmp_path / "displaced-publication"
    rename_no_replace = publication_module._rename_no_replace
    foreign_staging: Path | None = None

    def replace_after_install(staging: Path, target: Path) -> None:
        nonlocal foreign_staging
        rename_no_replace(staging, target)
        target.rename(displaced)
        target.mkdir()
        (target / "foreign.txt").write_text("replacement", encoding="utf-8")
        foreign_staging = staging

    monkeypatch.setattr(publication_module, "_rename_no_replace", replace_after_install)

    with pytest.raises(OSError, match="changed during publication"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists()
    assert foreign_staging is not None
    assert (foreign_staging / "foreign.txt").read_text(encoding="utf-8") == (
        "replacement"
    )
    assert (displaced / "goldilocks.json").is_file()


def test_directory_publication_rechecks_public_identity_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "replaced-after-verification"
    displaced = tmp_path / "displaced-after-verification"
    verify_descriptor = publication_module._verify_directory_descriptor
    verification_count = 0

    def replace_after_post_install_verification(descriptor: int, files) -> None:
        nonlocal verification_count
        verify_descriptor(descriptor, files)
        verification_count += 1
        if verification_count == 3:
            destination.rename(displaced)
            destination.mkdir()
            (destination / "foreign.txt").write_text("foreign", encoding="utf-8")

    monkeypatch.setattr(
        publication_module,
        "_verify_directory_descriptor",
        replace_after_post_install_verification,
    )

    with pytest.raises(OSError, match="destination changed during publication"):
        Publisher().publish(input_data, DirectoryOutput(destination))

    assert not destination.exists(follow_symlinks=False)
    assert (displaced / "goldilocks.json").is_file()
    quarantined = list(tmp_path.glob(".replaced-after-verification.quarantine-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "foreign.txt").read_text(encoding="utf-8") == "foreign"


def test_archive_writes_remain_bound_to_open_staging_descriptor_after_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "descriptor-bound.zip"
    displaced = tmp_path / "displaced-descriptor-archive"
    descriptor_identity = publication_module._descriptor_identity
    foreign_staging: Path | None = None

    def replace_after_descriptor_open(descriptor: int) -> tuple[int, int]:
        nonlocal foreign_staging
        identity = descriptor_identity(descriptor)
        staging = next(tmp_path.glob(".descriptor-bound.zip.*"))
        staging.rename(displaced)
        staging.write_bytes(b"foreign staging archive")
        foreign_staging = staging
        return identity

    monkeypatch.setattr(
        publication_module,
        "_descriptor_identity",
        replace_after_descriptor_open,
    )

    with pytest.raises(OSError, match="staging changed during publication"):
        Publisher().publish(input_data, ArchiveOutput(destination))

    assert not destination.exists()
    assert foreign_staging is not None
    assert foreign_staging.read_bytes() == b"foreign staging archive"
    assert displaced.read_bytes() != b"foreign staging archive"
    assert displaced.stat().st_size > 0


def test_archive_identity_mismatch_quarantines_only_foreign_inode_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "only-foreign-copy.zip"
    displaced = tmp_path / "displaced-owned-archive-copy"
    link = publication_module.os.link

    def link_replacement_then_remove_staging(staging: Path, target: Path) -> None:
        staging.rename(displaced)
        staging.write_bytes(b"only foreign inode copy")
        link(staging, target)
        staging.unlink()

    monkeypatch.setattr(
        publication_module.os,
        "link",
        link_replacement_then_remove_staging,
    )

    with pytest.raises(OSError, match="changed during publication"):
        Publisher().publish(input_data, ArchiveOutput(destination))

    assert not destination.exists()
    quarantined = list(tmp_path.glob(".only-foreign-copy.zip.quarantine-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"only foreign inode copy"
    assert displaced.is_file()


def test_archive_publication_preserves_concurrent_in_place_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "modified.zip"
    link = publication_module.os.link

    def modify_after_link(staging: Path, target: Path) -> None:
        link(staging, target)
        target.write_bytes(b"foreign in-place write")

    monkeypatch.setattr(publication_module.os, "link", modify_after_link)

    with pytest.raises(OSError, match="Published archive checksum differs"):
        Publisher().publish(input_data, ArchiveOutput(destination))

    assert destination.read_bytes() == b"foreign in-place write"


@pytest.mark.parametrize("replacement_timing", ("before_link", "after_link"))
def test_archive_publication_never_overwrites_or_deletes_foreign_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_timing: str,
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "raced.zip"
    link = publication_module.os.link

    def race(staging: Path, target: Path) -> None:
        if replacement_timing == "before_link":
            target.write_bytes(b"foreign before link")
            link(staging, target)
            return
        link(staging, target)
        target.unlink()
        target.write_bytes(b"foreign after link")

    monkeypatch.setattr(publication_module.os, "link", race)

    error = FileExistsError if replacement_timing == "before_link" else OSError
    message = (
        "already exists"
        if replacement_timing == "before_link"
        else "changed during publication"
    )
    with pytest.raises(error, match=message):
        Publisher().publish(input_data, ArchiveOutput(destination))

    expected = f"foreign {replacement_timing.replace('_', ' ')}".encode()
    if replacement_timing == "before_link":
        assert destination.read_bytes() == expected
    else:
        assert not destination.exists()
        quarantined = list(tmp_path.glob(".raced.zip.quarantine-*"))
        assert len(quarantined) == 1
        assert quarantined[0].read_bytes() == expected


def test_archive_cleanup_never_removes_a_foreign_staging_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.publication as publication_module

    input_data, _, _ = _explicit_input_data(tmp_path)
    destination = tmp_path / "must-stay-absent.zip"
    displaced = tmp_path / "displaced-owned-archive"
    foreign_staging: Path | None = None

    def replace_staging_then_fail(staging: Path, target: Path) -> None:
        nonlocal foreign_staging
        del target
        staging.rename(displaced)
        staging.write_bytes(b"foreign archive staging")
        foreign_staging = staging
        raise FileExistsError("forced no-replace race")

    monkeypatch.setattr(publication_module.os, "link", replace_staging_then_fail)

    with pytest.raises(FileExistsError, match="already exists"):
        Publisher().publish(input_data, ArchiveOutput(destination))

    assert not destination.exists()
    assert foreign_staging is not None
    assert foreign_staging.read_bytes() == b"foreign archive staging"
    assert displaced.is_file()


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
    pseudo_bytes = b"<UPF version='2.0.1'>service fixture</UPF>\n"
    pseudo_path.write_bytes(pseudo_bytes)
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
                    content_sha256=hashlib.sha256(pseudo_bytes).hexdigest(),
                    content_size_bytes=len(pseudo_bytes),
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
                "schema_version": 2,
                "id": "pseudopotentials/fixture-table",
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

    assert pseudo.source.asset_id == "pseudopotentials/fixture-table"
    assert pseudo.source.asset_version == "1"
    assert pseudo.source.path == "pseudos/Si.UPF"
    assert licence.source.asset_id == "pseudopotentials/fixture-table"
    assert licence.source.asset_version == "1"
    assert licence.source.path == "LICENSE.txt"
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

    manifest_path = (
        store.root / "pseudopotentials" / "fixture-table" / "1" / "manifest.json"
    )
    installed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wrong_preparation = {
        **installed_manifest,
        "preparation_fingerprint": "0" * 64,
    }
    manifest_path.write_text(json.dumps(wrong_preparation), encoding="utf-8")
    with pytest.raises(ValueError, match="installed preparation differs"):
        Publisher(store).files(input_data)
    manifest_path.write_text(json.dumps(installed_manifest), encoding="utf-8")

    replacement = pseudo_bytes.replace(b"exact", b"other")
    assert len(replacement) == len(pseudo_bytes)
    (
        store.root / "pseudopotentials" / "fixture-table" / "1" / "pseudos" / "Si.UPF"
    ).write_bytes(replacement)
    for entry in installed_manifest["files"]:
        if entry["path"] == "pseudos/Si.UPF":
            entry["sha256"] = hashlib.sha256(replacement).hexdigest()
            entry["size"] = len(replacement)
    manifest_path.write_text(json.dumps(installed_manifest), encoding="utf-8")
    store.verify(table.asset.id, "1")

    with pytest.raises(ValueError, match="differs from its DFT Input Data descriptor"):
        Publisher(store).files(input_data)
    assert pseudo.source.preparation_fingerprint == table.asset.preparation_fingerprint


def _stub_metallicity(
    monkeypatch: pytest.MonkeyPatch, *, source: str = "model"
) -> None:
    result = (
        ("insulator", "model", 0.9)
        if source == "model"
        else ("unknown", "heuristic", None)
    )
    monkeypatch.setattr(
        "goldilocks_core.runtime.models.MetallicityModel.__call__",
        lambda self, structure: result,
    )


def test_model_runtime_identities_licences_and_citations_are_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_metallicity(monkeypatch)
    store = AssetStore(tmp_path / "model-assets")
    expected_licences: dict[str, bytes] = {}
    model_payloads: set[bytes] = set()
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
        model_payloads.update(
            contents[file.path] for file in spec.files if file.role != "licence"
        )
        expected_licences[f"licences/{spec.id.replace('/', '_')}-{spec.version}.md"] = (
            next(contents[file.path] for file in spec.files if file.role == "licence")
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
    request = ComputeRequest(
        replace(request.draft, hints=CalculationHints(pseudo_type="NC")),
        request.selection,
    )
    with Runtime(asset_store=store) as runtime:
        with Service(runtime) as service:
            result = service.compute(request)

    input_data = result.records[DftInputData]
    assert {item.id for item in input_data.runtime.assets} == {
        "models/qrf-kpoints",
        "models/metallicity-cgcnn",
    }
    assert {model["target"] for model in input_data.runtime.models} == {
        "k_distance",
        "metallicity",
    }
    specs = {spec.id: spec for spec in model_asset_specs()}
    for identity in input_data.runtime.assets:
        spec = specs[identity.id]
        installed = store.verify_spec(spec)
        assert identity.preparation_fingerprint == spec.preparation_fingerprint
        assert identity.model in input_data.runtime.models
        assert identity.files == tuple(
            {
                "path": file.path,
                "role": next(
                    source.role for source in spec.files if source.path == file.path
                ),
                "sha256": file.sha256,
                "size_bytes": file.size,
            }
            for file in installed.files
        )
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
    published_files = Publisher(store).files(input_data)
    files = {item.path: item.content for item in published_files}
    assert {path: files[path] for path in expected_licences} == expected_licences
    published_manifest = json.loads(files["goldilocks.json"])
    assert published_manifest["runtime"]["assets"] == [
        identity.to_dict() for identity in input_data.runtime.assets
    ]
    assert all(
        "preparation_fingerprint" in identity
        and identity["model"] in published_manifest["runtime"]["models"]
        and all(
            set(file) == {"path", "role", "sha256", "size_bytes"}
            for file in identity["files"]
        )
        for identity in published_manifest["runtime"]["assets"]
    )
    assert all(payload not in files["goldilocks.json"] for payload in model_payloads)
    model_citation = (
        "Elena Patyukova et al., Automatic generation of input files with optimised "
        "k-point meshes for Quantum ESPRESSO self-consistent field single-point "
        "total energy calculations, Digital Discovery (2026), "
        "DOI 10.1039/D5DD00565E."
    )
    expected_citations = {model_citation}
    licence_urls = {
        file.url
        for spec in model_asset_specs()
        for file in spec.files
        if file.role == "licence"
    }
    assert set(input_data.citations) >= expected_citations
    assert input_data.citations.count(model_citation) == 1
    assert set(input_data.citations).isdisjoint(licence_urls)
    assert str(store.root) not in str(input_data.to_dict())


def test_custom_registry_same_id_version_source_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import goldilocks_core.ml.model_registry as registry_module

    _stub_metallicity(monkeypatch)

    registry = tmp_path / "models.toml"
    packaged = Path(registry_module.__file__).with_name("registry.toml")
    registry.write_text(packaged.read_text(encoding="utf-8"), encoding="utf-8")
    config = registry_module.load_default_qrf_config(registry)
    store = AssetStore(tmp_path / "drift-assets")
    for spec in (config.model_asset, config.metallicity_asset):
        assert spec is not None
        _create_installed_asset(
            store,
            spec,
            {file.path: f"installed {file.role}\n".encode() for file in spec.files},
        )

    def predict(self, structure: Structure) -> KPointSelection:
        del self, structure
        return KPointSelection(
            grid=(4, 4, 4),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="model", reason="Fixture prediction."),
        )

    monkeypatch.setattr("goldilocks_core.advice.kdistance.QrfBackend.__call__", predict)
    request = _explicit_request(tmp_path, "registry-drift-Si.UPF")
    request = ComputeRequest(
        replace(request.draft, hints=CalculationHints(pseudo_type="NC")),
        request.selection,
    )
    with Runtime(asset_store=store, registry_path=registry) as runtime:
        with Service(runtime) as service:
            original = service.compute(request).records[DftInputData]
    original_fingerprints = {
        asset.id: asset.preparation_fingerprint for asset in original.runtime.assets
    }

    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "/75588288f755522e47984b5a31b82824860d6943/QRF95.pkl",
            "/foreign-registry-revision/QRF95.pkl",
            1,
        ),
        encoding="utf-8",
    )
    drifted = registry_module.load_default_qrf_config(registry)
    assert drifted.model_asset is not None
    assert drifted.model_asset.id == config.model_asset.id
    assert drifted.model_asset.version == config.model_asset.version
    assert (
        drifted.model_asset.preparation_fingerprint
        != original_fingerprints[drifted.model_asset.id]
    )

    with Runtime(asset_store=store, registry_path=registry) as runtime:
        with Service(runtime) as service:
            with pytest.raises(ValueError, match="installed preparation differs"):
                service.compute(request)


def test_unidentified_runtime_kmesh_model_is_not_attributed_to_defaults(
    tmp_path: Path,
) -> None:
    class UnidentifiedModel:
        def __call__(self, structure: Structure) -> KPointSelection:
            del structure
            return KPointSelection(
                grid=(4, 4, 4),
                shift=(0, 0, 0),
                mesh_type="monkhorst-pack",
                provenance=Provenance(
                    source="model",
                    reason="Unidentified runtime model.",
                ),
            )

        def reset(self) -> None:
            pass

        def close(self) -> None:
            pass

    request = _explicit_request(tmp_path, "unidentified-model-Si.UPF")
    request = ComputeRequest(
        replace(request.draft, hints=CalculationHints(pseudo_type="NC")),
        request.selection,
    )
    with Runtime(
        asset_store=AssetStore(tmp_path / "empty-assets"),
        kmesh_service=UnidentifiedModel(),
    ) as runtime:
        with Service(runtime) as service:
            with pytest.raises(
                ValueError,
                match="Custom KMeshService produced a model result without identity",
            ):
                service.compute(request)


def test_standalone_metallicity_publishes_only_its_explicit_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from goldilocks_core.runtime.models import MetallicityModel

    def classify(self, structure):
        del self, structure
        return "insulator", "model", 0.91

    monkeypatch.setattr(MetallicityModel, "__call__", classify)
    citation = "A. Scientist, Operator metallicity model (2026)."
    model = ModelSpec(
        name="operator-metallicity",
        version="2026.1",
        model_type="cgcnn",
        target="metallicity",
        feature_set="operator-radius-graph",
        source="local",
        location=str(tmp_path / "model.ckpt"),
        licence="Operator-Model-Licence-1.0",
        licence_text="Operator metallicity model terms.\n",
        citation=citation,
    )
    request = _explicit_request(tmp_path, "identified-metallicity-Si.UPF")
    with Runtime(
        asset_store=AssetStore(tmp_path / "empty-assets"),
        metallicity_checkpoint="model.ckpt",
        metallicity_atom_init="atom-init.json",
        metallicity_model=model,
    ) as runtime:
        with Service(runtime) as service:
            result = service.compute(request)

    input_data = result.records[DftInputData]
    assert input_data.runtime.assets == ()
    assert input_data.runtime.models == (
        {
            "name": "operator-metallicity",
            "version": "2026.1",
            "model_type": "cgcnn",
            "target": "metallicity",
            "feature_set": "operator-radius-graph",
            "source": "local",
            "revision": None,
            "licence": "Operator-Model-Licence-1.0",
            "citation": citation,
        },
    )
    assert input_data.citations == (
        "Fixture pseudopotential citation.",
        citation,
    )
    files = {item.path: item.content for item in Publisher().files(input_data)}
    assert files["licences/custom-metallicity-model.txt"] == (
        b"Operator metallicity model terms.\n"
    )
    assert str(tmp_path) not in str(input_data.to_dict())


def test_custom_kmesh_model_publishes_its_explicit_material_not_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_metallicity(monkeypatch, source="heuristic")
    monkeypatch.setattr(
        "goldilocks_core.advice.kindex.predict_kindex",
        lambda structure, spec: 1.0,
    )
    licence_text = "Custom model redistribution terms.\n"
    citation = "A. Scientist, Custom k-index model (2026)."
    custom = ModelSpec(
        name="operator-kindex",
        version="2026.1",
        model_type="random_forest",
        target="k_index",
        feature_set="operator-features",
        source="local",
        location=str(tmp_path / "operator.joblib"),
        licence="Operator-Model-Licence-1.0",
        licence_text=licence_text,
        citation=citation,
    )
    request = _explicit_request(tmp_path, "custom-model-Si.UPF")
    request = ComputeRequest(
        replace(
            request.draft,
            hints=CalculationHints(pseudo_type="NC"),
            kmesh_model=custom,
        ),
        request.selection,
    )
    store = AssetStore(tmp_path / "empty-assets")
    unused_registry = tmp_path / "unused-default-models.toml"
    unused_registry.write_text("[defaults]\n", encoding="utf-8")

    with Runtime(asset_store=store, registry_path=unused_registry) as runtime:
        with Service(runtime) as service:
            result = service.compute(request)

    input_data = result.records[DftInputData]
    assert input_data.runtime.assets == ()
    assert [model["name"] for model in input_data.runtime.models] == ["operator-kindex"]
    assert input_data.citations == (
        "Fixture pseudopotential citation.",
        citation,
    )
    files = {item.path: item.content for item in Publisher(store).files(input_data)}
    assert files["licences/custom-kmesh-model.txt"] == licence_text.encode()
    assert str(tmp_path) not in str(input_data.to_dict())
    serialized_result = json.dumps(result.to_dict())
    assert str(tmp_path) not in serialized_result
    assert licence_text not in serialized_result


def test_same_name_version_models_with_different_targets_and_revisions_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from goldilocks_core.runtime.models import MetallicityModel

    monkeypatch.setattr(
        "goldilocks_core.advice.kindex.predict_kindex",
        lambda structure, spec: 1.0,
    )
    monkeypatch.setattr(
        MetallicityModel,
        "__call__",
        lambda self, structure: ("insulator", "model", 0.91),
    )
    common = {
        "name": "shared-operator-model",
        "version": "1",
        "source": "local",
        "licence": "Operator-Model-Licence-1.0",
        "licence_text": "Operator model terms.\n",
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
            input_data = service.compute(request).records[DftInputData]

    assert [model["target"] for model in input_data.runtime.models] == [
        "k_index",
        "metallicity",
    ]
    assert [model["revision"] for model in input_data.runtime.models] == [
        "kmesh-revision",
        "metallicity-revision",
    ]
    licence_paths = {
        artifact.path for artifact in input_data.artifacts if artifact.role == "licence"
    }
    assert {
        "licences/custom-kmesh-model.txt",
        "licences/custom-metallicity-model.txt",
    } <= licence_paths
    assert {"K-mesh model citation.", "Metallicity model citation."} <= set(
        input_data.citations
    )


def test_custom_kmesh_model_without_publication_material_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "goldilocks_core.advice.kindex.predict_kindex",
        lambda structure, spec: 1.0,
    )
    request = _explicit_request(tmp_path, "incomplete-custom-model-Si.UPF")
    request = ComputeRequest(
        replace(
            request.draft,
            hints=CalculationHints(pseudo_type="NC"),
            kmesh_model=ModelSpec(
                name="incomplete-operator-model",
                version="1",
                model_type="random_forest",
                target="k_index",
                feature_set="operator-features",
                source="local",
                location=str(tmp_path / "operator.joblib"),
            ),
        ),
        request.selection,
    )

    with Runtime(asset_store=AssetStore(tmp_path / "empty-assets")) as runtime:
        with Service(runtime) as service:
            with pytest.raises(
                ValueError,
                match=(
                    "Model 'incomplete-operator-model' used for publication must "
                    "declare non-empty licence, licence_text, and citation"
                ),
            ):
                service.compute(request)


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
    assert "Fixture licence text" not in serialized
    assert "service fixture" not in serialized
    assert "pseudo_info" not in serialized
    assert document["records"]["dft_input_data"]["artifacts"][0]["source"] == {
        "kind": "generated",
        "identity": document["records"]["dft_input_data"]["artifacts"][0]["source"][
            "identity"
        ],
    }


def test_staging_creation_failure_never_creates_explicit_destination(
    tmp_path: Path,
) -> None:
    input_data, _, _ = _explicit_input_data(tmp_path)
    publisher = Publisher()
    for output_type in (DirectoryOutput, ArchiveOutput):
        destination = tmp_path / ("x" * 250)
        with pytest.raises(OSError):
            publisher.publish(input_data, output_type(destination))
        assert not destination.exists()
