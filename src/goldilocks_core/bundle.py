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
        result: Completed Core result, usually including generated files
            from Generate mode.

    Returns:
        Manifest dictionary with schema version, serialized intent, analysis,
        advice, selection, generated-file metadata, and warnings. Generated
        file content is not embedded.
    """
    files = [
        {
            "path": generated_file.path,
            "role": generated_file.role,
            "bytes": len(generated_file.content.encode("utf-8")),
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
    """Write generated files and manifest to a deterministic bundle directory.

    Args:
        result: Completed Core result with generated files to write.
        output_dir: Bundle root directory. It is created if needed.

    Returns:
        ``BundleRecord`` carrying the bundle path and the manifest dictionary
        also written to ``manifest.json``.

    Raises:
        ValueError: If a generated file path would escape ``output_dir``.
    """
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for generated_file in result.generated_files:
        target_path = _resolve_bundle_path(target_dir, generated_file.path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(generated_file.content, encoding="utf-8")

    manifest = build_bundle_manifest(result)
    manifest_path = target_dir / MANIFEST_FILENAME
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
