"""Bundle-stage portable directory output."""

from __future__ import annotations

import json
from pathlib import Path

from goldilocks_core.contracts import BundleRecord, CoreResult, JsonDict

MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1


def build_bundle_manifest(result: CoreResult) -> JsonDict:
    """Return a JSON-safe manifest for a Core output bundle.

    Args:
        result: Completed Core result, usually including generated files from
            Generate mode.

    Returns:
        Manifest dictionary with schema version, serialized intent, analysis,
        advice, selection, generated-file metadata, and warnings. Generated file
        content is not embedded.
    """
    files = [
        {
            "path": generated_file.path,
            "role": generated_file.role,
        }
        for generated_file in result.generated_files
    ]

    return {
        "manifest_version": MANIFEST_VERSION,
        "intent": result.intent.to_dict(),
        "analysis": result.analysis.to_dict(),
        "advice": result.advice.to_dict(),
        "selection": result.selection.to_dict(),
        "generated_files": files,
        "warnings": list(result.warnings),
    }


def write_bundle_directory(
    result: CoreResult,
    output_dir: str | Path,
) -> BundleRecord:
    """Write generated files and a manifest to a new bundle directory.

    Args:
        result: Completed Core result with generated files to write.
        output_dir: New bundle root directory. Its parent directories are
            created if needed, but the bundle directory must not already exist.

    Returns:
        ``BundleRecord`` with the output directory path and manifest.

    Raises:
        FileExistsError: If ``output_dir`` already exists.
        ValueError: If a generated file path would escape ``output_dir`` or is
            reserved for the manifest.
    """
    target_dir = Path(output_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if target_dir.exists():
        raise FileExistsError(f"Bundle destination already exists: {target_dir}")

    manifest_path = target_dir / MANIFEST_FILENAME
    files = tuple(
        (generated_file, _resolve_bundle_path(target_dir, generated_file.path))
        for generated_file in result.generated_files
    )
    if len({path for _, path in files}) != len(files):
        raise ValueError("Generated file paths must be unique")
    for generated_file, target_path in files:
        if target_path == manifest_path or manifest_path in target_path.parents:
            raise ValueError(
                "Generated file path is reserved for the bundle manifest: "
                f"{generated_file.path}"
            )

    target_dir.mkdir(parents=True, exist_ok=False)

    for generated_file, target_path in files:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(generated_file.content, encoding="utf-8")

    manifest = build_bundle_manifest(result)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return BundleRecord(path=str(output_dir), manifest=manifest)


def _resolve_bundle_path(output_dir: Path, relative_path: str) -> Path:
    """Resolve a generated file path without allowing path traversal."""
    target_path = (output_dir / relative_path).resolve()
    root = output_dir.resolve()

    if target_path == root or root not in target_path.parents:
        raise ValueError(
            f"Generated file path escapes bundle directory: {relative_path}"
        )

    return target_path
