import json
from dataclasses import replace
from pathlib import Path

import pytest

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
    }
    assert bundle_record.path == str(output_dir)
    assert {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    } == {"inputs/qe.in", "manifest.json"}


@pytest.mark.parametrize("destination_kind", ["file", "directory"])
def test_write_bundle_refuses_existing_destination(
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


@pytest.mark.parametrize("path", ["manifest.json", "manifest.json/nested"])
def test_write_bundle_rejects_manifest_collision(tmp_path: Path, path: str) -> None:
    """Reject a generated file path that would conflict with the manifest."""
    result = replace(
        make_result(),
        generated_files=(GeneratedFile(path=path, content="collision"),),
    )
    output_dir = tmp_path / "bundle"

    with pytest.raises(ValueError, match="reserved for the bundle manifest"):
        write_bundle_directory(result, output_dir)

    assert not output_dir.exists()


def test_bundle_rejects_duplicate_paths(tmp_path: Path) -> None:
    """Refuse ambiguous output rather than overwrite an earlier file."""
    generated = make_result().generated_files[0]
    result = replace(make_result(), generated_files=(generated, generated))

    with pytest.raises(ValueError, match="paths must be unique"):
        write_bundle_directory(result, tmp_path / "bundle")


def test_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    """Keep generated files inside the bundle directory."""
    result = replace(
        make_result(),
        generated_files=(GeneratedFile(path="../qe.in", content="bad"),),
    )

    with pytest.raises(ValueError, match="escapes bundle directory"):
        write_bundle_directory(result, tmp_path / "bundle")

    assert not (tmp_path / "qe.in").exists()
