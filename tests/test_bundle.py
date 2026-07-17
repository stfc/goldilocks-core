import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

import goldilocks_core.bundle as bundle_module
from goldilocks_core.advice import advise_parameters
from goldilocks_core.bundle import build_bundle_manifest, write_bundle_directory
from goldilocks_core.contracts import (
    CalculationIntent,
    CoreResult,
    GeneratedFile,
    KPointSelection,
    Provenance,
    SelectionRecord,
    StructureAnalysisRecord,
)


def make_result() -> CoreResult:
    """Build a minimal Core result with one generated file."""
    analysis = StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
    )
    advice = advise_parameters(analysis)
    selection = SelectionRecord(
        k_points=KPointSelection(
            grid=(4, 4, 4),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="default", reason="test"),
        ),
        pseudopotentials=(),
    )
    return CoreResult(
        intent=CalculationIntent(),
        analysis=analysis,
        advice=advice,
        selection=selection,
        generated_files=(GeneratedFile(path="inputs/qe.in", content="&CONTROL\n/\n"),),
        warnings=("test warning",),
    )


def test_build_bundle_manifest_records_file_metadata_without_content() -> None:
    """Build a manifest containing stage outputs and generated file metadata."""
    manifest = build_bundle_manifest(make_result())

    assert manifest["manifest_version"] == 1
    assert manifest["intent"]["code"] == "quantum_espresso"
    assert manifest["analysis"]["elements"] == ["Si"]
    assert manifest["advice"]["k_points"]["mesh_type"] == "monkhorst-pack"
    assert manifest["selection"]["k_points"]["grid"] == [4, 4, 4]
    assert manifest["generated_files"] == [
        {
            "path": "inputs/qe.in",
            "role": "input",
            "bytes": 11,
            "sha256": (
                "49dae8eb457ab713c57c31c2cfb45e31a56d5aae75cd9eb244c3cb4009e3514d"
            ),
        }
    ]
    assert manifest["warnings"] == ["test warning"]


def test_write_bundle_directory_writes_manifest_and_files(tmp_path: Path) -> None:
    """Write a deterministic bundle layout to disk."""
    result = make_result()
    output_dir = tmp_path / "bundle"

    bundle_record = write_bundle_directory(result, output_dir)

    written_content = (output_dir / "inputs" / "qe.in").read_bytes()
    assert written_content == b"&CONTROL\n/\n"
    manifest_data = json.loads(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_data == bundle_record.manifest
    assert manifest_data["generated_files"][0] == {
        "path": "inputs/qe.in",
        "role": "input",
        "bytes": len(written_content),
        "sha256": "49dae8eb457ab713c57c31c2cfb45e31a56d5aae75cd9eb244c3cb4009e3514d",
    }
    assert bundle_record.path == str(output_dir)
    assert {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    } == {"inputs/qe.in", "manifest.json"}
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


@pytest.mark.parametrize("destination_kind", ["file", "directory"])
def test_write_bundle_refuses_existing_destination_without_modifying_it(
    tmp_path: Path,
    destination_kind: str,
) -> None:
    """Refuse both file and directory destinations without overwriting data."""
    output_dir = tmp_path / "bundle"
    if destination_kind == "file":
        output_dir.write_text("keep me", encoding="utf-8")
    else:
        output_dir.mkdir()
        (output_dir / "stale.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        write_bundle_directory(make_result(), output_dir)

    if destination_kind == "file":
        assert output_dir.read_text(encoding="utf-8") == "keep me"
    else:
        assert [path.name for path in output_dir.iterdir()] == ["stale.txt"]
        assert (output_dir / "stale.txt").read_text(encoding="utf-8") == "keep me"
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


@pytest.mark.parametrize("invalid_path", ["../qe.in", "inputs/../../qe.in"])
def test_write_bundle_preflights_traversal_before_creating_destination(
    tmp_path: Path,
    invalid_path: str,
) -> None:
    """Reapply GeneratedFile validation before staging any output."""
    result = make_result()
    invalid_file = replace(result.generated_files[0])
    object.__setattr__(invalid_file, "path", invalid_path)
    object.__setattr__(result, "generated_files", (invalid_file,))
    output_dir = tmp_path / "bundle"

    with pytest.raises(ValueError, match="must not contain '..' traversal"):
        write_bundle_directory(result, output_dir)

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_write_bundle_preflights_duplicates_before_creating_destination(
    tmp_path: Path,
) -> None:
    """Reapply CoreResult duplicate validation before staging any output."""
    result = make_result()
    duplicate = GeneratedFile(path="inputs/qe.in", content="duplicate")
    object.__setattr__(
        result,
        "generated_files",
        (result.generated_files[0], duplicate),
    )
    output_dir = tmp_path / "bundle"

    with pytest.raises(ValueError, match="duplicate path"):
        write_bundle_directory(result, output_dir)

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


@pytest.mark.parametrize(
    "generated_files",
    [
        (GeneratedFile(path="manifest.json", content="collision"),),
        (GeneratedFile(path="manifest.json/part", content="collision"),),
        (
            GeneratedFile(path="inputs", content="file"),
            GeneratedFile(path="inputs/qe.in", content="child"),
        ),
    ],
)
def test_write_bundle_preflights_layout_conflicts_before_creating_destination(
    tmp_path: Path,
    generated_files: tuple[GeneratedFile, ...],
) -> None:
    """Reject paths that cannot coexist with the complete bundle layout."""
    result = replace(make_result(), generated_files=generated_files)
    output_dir = tmp_path / "bundle"

    with pytest.raises(ValueError, match="reserved|conflict"):
        write_bundle_directory(result, output_dir)

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


@pytest.mark.parametrize(
    "generated_files",
    [
        (
            GeneratedFile(path="inputs/A.in", content="first"),
            GeneratedFile(path="inputs/a.in", content="second"),
        ),
        (
            GeneratedFile(path="inputs\\qe.in", content="first"),
            GeneratedFile(path="inputs/qe.in", content="second"),
        ),
        (
            GeneratedFile(path="Inputs\\A.in", content="first"),
            GeneratedFile(path="inputs/a.in", content="second"),
        ),
    ],
)
def test_write_bundle_preflights_windows_path_collisions_without_windows(
    tmp_path: Path,
    generated_files: tuple[GeneratedFile, ...],
) -> None:
    """Reject paths that collide under Windows separator or case semantics."""
    result = replace(make_result(), generated_files=generated_files)

    with pytest.raises(ValueError, match="collide on the target filesystem"):
        bundle_module._preflight_bundle(
            result,
            tmp_path / "bundle",
            target_is_windows=True,
        )

    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_windows_path_key_reserves_case_equivalent_manifest_without_windows(
    tmp_path: Path,
) -> None:
    """Treat the manifest name as case-insensitive for a Windows target."""
    result = replace(
        make_result(),
        generated_files=(GeneratedFile(path="MANIFEST.JSON", content="collision"),),
    )

    with pytest.raises(ValueError, match="reserved"):
        bundle_module._preflight_bundle(
            result,
            tmp_path / "bundle",
            target_is_windows=True,
        )


@pytest.mark.parametrize(
    "invalid_path",
    [
        "inputs/a.",
        "inputs/a ",
        "manifest.json.",
        "manifest.json ",
        "nested/manifest.json ",
        "inputs/CON.txt",
        "inputs/con .txt",
        "inputs/COM¹.log",
        "inputs/LPT9",
        "inputs/CONIN$.txt",
        "inputs/qe.in:metadata",
        'inputs/q"e.in',
        "inputs/q*e.in",
        "inputs/q<e.in",
        "inputs/q>e.in",
        "inputs/q?e.in",
        "inputs/q|e.in",
        "inputs/q\x01e.in",
    ],
)
def test_windows_target_rejects_invalid_components_without_windows(
    tmp_path: Path,
    invalid_path: str,
) -> None:
    """Reject Win32-invalid components before creating output."""
    result = replace(
        make_result(),
        generated_files=(GeneratedFile(path=invalid_path, content="invalid"),),
    )

    with pytest.raises(ValueError, match="component invalid for Windows"):
        bundle_module._preflight_bundle(
            result,
            tmp_path / "bundle",
            target_is_windows=True,
        )

    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_posix_target_preserves_backslash_and_case_distinct_paths() -> None:
    """Keep legal POSIX backslash and case variants as distinct paths."""
    backslash_key = bundle_module._target_filesystem_path_key(
        Path("inputs\\qe.in"),
        windows=False,
    )
    slash_key = bundle_module._target_filesystem_path_key(
        Path("inputs/qe.in"),
        windows=False,
    )
    upper_case_key = bundle_module._target_filesystem_path_key(
        Path("inputs/A.in"),
        windows=False,
    )
    lower_case_key = bundle_module._target_filesystem_path_key(
        Path("inputs/a.in"),
        windows=False,
    )

    assert backslash_key != slash_key
    assert upper_case_key != lower_case_key


@pytest.mark.skipif(os.name == "nt", reason="backslash is a Windows separator")
def test_write_bundle_keeps_valid_posix_distinct_paths(tmp_path: Path) -> None:
    """Write legal POSIX backslash and case-distinct generated paths."""
    result = replace(
        make_result(),
        generated_files=(
            GeneratedFile(path="inputs\\qe.in", content="backslash"),
            GeneratedFile(path="inputs/qe.in", content="slash"),
            GeneratedFile(path="inputs/A.in", content="upper case"),
            GeneratedFile(path="inputs/a.in", content="lower case"),
            GeneratedFile(path="inputs/CON.txt", content="device name"),
            GeneratedFile(path="inputs/a.", content="trailing period"),
            GeneratedFile(path="inputs/qe.in:metadata", content="colon"),
        ),
    )
    output_dir = tmp_path / "bundle"

    write_bundle_directory(result, output_dir)

    assert (output_dir / "inputs\\qe.in").read_text(encoding="utf-8") == "backslash"
    assert (output_dir / "inputs" / "qe.in").read_text(encoding="utf-8") == "slash"
    assert (output_dir / "inputs" / "A.in").read_text(encoding="utf-8") == "upper case"
    assert (output_dir / "inputs" / "a.in").read_text(encoding="utf-8") == "lower case"
    assert (output_dir / "inputs" / "CON.txt").read_text(
        encoding="utf-8"
    ) == "device name"
    assert (output_dir / "inputs" / "a.").read_text(
        encoding="utf-8"
    ) == "trailing period"
    assert (output_dir / "inputs" / "qe.in:metadata").read_text(
        encoding="utf-8"
    ) == "colon"


def test_publication_uses_darwin_no_replace_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch macOS publication through renamex_np(RENAME_EXCL)."""
    calls = []

    class RenameExclusive:
        argtypes = None
        restype = None

        def __call__(self, source, target, flags):
            calls.append((source, target, flags))
            return 0

    class DarwinLibc:
        renamex_np = RenameExclusive()

    monkeypatch.setattr(bundle_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        bundle_module.ctypes,
        "CDLL",
        lambda *args, **kwargs: DarwinLibc(),
    )
    source = tmp_path / "staging"
    target = tmp_path / "bundle"

    bundle_module._publish_staged_directory(source, target)

    assert calls == [
        (
            os.fsencode(source),
            os.fsencode(target),
            bundle_module._RENAME_EXCL,
        )
    ]


def test_concurrent_destination_is_not_replaced_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use no-replace publication if a destination appears after preflight."""
    original_publish = bundle_module._publish_staged_directory
    competing_inode = None

    def create_competing_destination(staging_dir: Path, target_dir: Path) -> None:
        nonlocal competing_inode
        target_dir.mkdir()
        competing_inode = target_dir.stat().st_ino
        original_publish(staging_dir, target_dir)

    monkeypatch.setattr(
        bundle_module,
        "_publish_staged_directory",
        create_competing_destination,
    )
    output_dir = tmp_path / "bundle"

    with pytest.raises(FileExistsError):
        write_bundle_directory(make_result(), output_dir)

    assert output_dir.is_dir()
    assert output_dir.stat().st_ino == competing_inode
    assert not list(output_dir.iterdir())
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_write_failure_removes_staging_without_publishing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove all staged bytes when a write fails before publication."""
    original_write_bytes = Path.write_bytes
    write_count = 0

    def fail_manifest_write(path: Path, data: bytes) -> int:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("injected write failure")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_manifest_write)
    output_dir = tmp_path / "bundle"

    with pytest.raises(OSError, match="injected write failure"):
        write_bundle_directory(make_result(), output_dir)

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_cleanup_retry_preserves_write_error_and_removes_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry cleanup without masking the write error that caused it."""
    original_write_bytes = Path.write_bytes
    original_rmtree = bundle_module.shutil.rmtree
    cleanup_calls = 0

    def fail_manifest_write(path: Path, data: bytes) -> int:
        if path.name == "manifest.json":
            raise OSError("injected write failure")
        return original_write_bytes(path, data)

    def fail_first_cleanup(path: Path) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise OSError("injected cleanup failure")
        original_rmtree(path)

    monkeypatch.setattr(Path, "write_bytes", fail_manifest_write)
    monkeypatch.setattr(bundle_module.shutil, "rmtree", fail_first_cleanup)

    with pytest.raises(OSError, match="injected write failure") as error:
        write_bundle_directory(make_result(), tmp_path / "bundle")

    assert error.value.__cause__ is None
    assert any(
        "completed after an earlier failure" in note for note in error.value.__notes__
    )
    assert cleanup_calls == 2
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


@pytest.mark.parametrize(
    ("failure_stage", "primary_message"),
    [
        ("write", "injected write failure"),
        ("publication", "injected publication failure"),
    ],
)
def test_cleanup_failure_preserves_primary_error_and_reports_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    primary_message: str,
) -> None:
    """Keep write and publication errors primary when cleanup cannot complete."""
    original_write_bytes = Path.write_bytes
    original_rmtree = bundle_module.shutil.rmtree

    def fail_manifest_write(path: Path, data: bytes) -> int:
        if path.name == "manifest.json":
            raise OSError(primary_message)
        return original_write_bytes(path, data)

    def fail_publication(staging_dir: Path, target_dir: Path) -> None:
        raise OSError(primary_message)

    def fail_cleanup(path: Path) -> None:
        raise OSError("injected cleanup failure")

    if failure_stage == "write":
        monkeypatch.setattr(Path, "write_bytes", fail_manifest_write)
    else:
        monkeypatch.setattr(
            bundle_module,
            "_publish_staged_directory",
            fail_publication,
        )
    monkeypatch.setattr(bundle_module.shutil, "rmtree", fail_cleanup)

    with pytest.raises(OSError, match=primary_message) as error:
        write_bundle_directory(make_result(), tmp_path / "bundle")

    staging_dirs = list(tmp_path.glob(".goldilocks-bundle-*"))
    assert error.value.__cause__ is None
    assert any("injected cleanup failure" in note for note in error.value.__notes__)
    assert any("residue remains" in note for note in error.value.__notes__)
    assert len(staging_dirs) == 1
    original_rmtree(staging_dirs[0])


@pytest.mark.parametrize(
    ("failure_stage", "primary_message"),
    [
        ("write", "injected write failure"),
        ("publication", "injected publication failure"),
    ],
)
def test_cleanup_probe_failure_preserves_primary_error_and_reports_unknown_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    primary_message: str,
) -> None:
    """Keep primary failures when cleanup cannot determine staging residue."""
    original_write_bytes = Path.write_bytes
    original_lexists = bundle_module.os.path.lexists
    primary_error = OSError(primary_message)
    staging_probe_calls = 0

    def fail_manifest_write(path: Path, data: bytes) -> int:
        if path.name == "manifest.json":
            raise primary_error
        return original_write_bytes(path, data)

    def fail_publication(staging_dir: Path, target_dir: Path) -> None:
        raise primary_error

    def fail_final_staging_probe(path: str | Path) -> bool:
        nonlocal staging_probe_calls
        if Path(path).name.startswith(".goldilocks-bundle-"):
            staging_probe_calls += 1
            if staging_probe_calls == 2:
                raise OSError("injected cleanup probe failure")
        return original_lexists(path)

    if failure_stage == "write":
        monkeypatch.setattr(Path, "write_bytes", fail_manifest_write)
    else:
        monkeypatch.setattr(
            bundle_module,
            "_publish_staged_directory",
            fail_publication,
        )
    monkeypatch.setattr(bundle_module.os.path, "lexists", fail_final_staging_probe)

    with pytest.raises(OSError) as error:
        write_bundle_directory(make_result(), tmp_path / "bundle")

    assert error.value is primary_error
    assert error.value.__cause__ is None
    assert any(
        "OSError: injected cleanup probe failure" in note
        for note in error.value.__notes__
    )
    assert any(
        "could not verify whether staging residue remains at" in note
        for note in error.value.__notes__
    )
    assert any(".goldilocks-bundle-" in note for note in error.value.__notes__)
    assert staging_probe_calls == 2
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_cleanup_probe_failure_after_publication_warns_without_failing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report an unverifiable post-publication cleanup check as a warning."""
    original_lexists = bundle_module.os.path.lexists

    def fail_staging_probe(path: str | Path) -> bool:
        if Path(path).name.startswith(".goldilocks-bundle-"):
            raise OSError("injected cleanup probe failure")
        return original_lexists(path)

    monkeypatch.setattr(bundle_module.os.path, "lexists", fail_staging_probe)
    output_dir = tmp_path / "bundle"

    with pytest.warns(RuntimeWarning) as warning_records:
        bundle_record = write_bundle_directory(make_result(), output_dir)

    assert bundle_record.path == str(output_dir)
    assert (output_dir / "manifest.json").is_file()
    assert len(warning_records) == 1
    warning_message = str(warning_records[0].message)
    assert "Bundle publication succeeded" in warning_message
    assert "OSError: injected cleanup probe failure" in warning_message
    assert "could not verify whether staging residue remains at" in warning_message
    assert ".goldilocks-bundle-" in warning_message
    assert "; staging residue remains at" not in warning_message
    assert not list(tmp_path.glob(".goldilocks-bundle-*"))


def test_generated_file_rejects_path_traversal_at_construction() -> None:
    """Reject generated paths before they can reach bundle writing."""
    with pytest.raises(ValueError, match="must not contain '..' traversal"):
        GeneratedFile(path="../qe.in", content="bad")
