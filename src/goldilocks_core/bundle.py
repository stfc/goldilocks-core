"""Bundle-stage portable directory output."""

from __future__ import annotations

import json
from pathlib import Path

from goldilocks_core.contracts import CoreRecommendation, JsonDict

MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1


def build_bundle_manifest(recommendation: CoreRecommendation) -> JsonDict:
    """Return a JSON-safe manifest for a Core output bundle."""
    files = [
        {
            "path": generated_file.path,
            "role": generated_file.role,
            "bytes": len(generated_file.content.encode("utf-8")),
        }
        for generated_file in recommendation.generated_files
    ]

    return {
        "manifest_version": MANIFEST_VERSION,
        "intent": recommendation.intent.to_dict(),
        "analysis": recommendation.analysis.to_dict(),
        "advice": recommendation.advice.to_dict(),
        "selection": recommendation.selection.to_dict(),
        "generated_files": files,
        "warnings": list(recommendation.warnings),
    }


def write_bundle_directory(
    recommendation: CoreRecommendation,
    output_dir: str | Path,
) -> JsonDict:
    """Write generated files and manifest to a deterministic bundle directory."""
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for generated_file in recommendation.generated_files:
        target_path = _resolve_bundle_path(target_dir, generated_file.path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(generated_file.content, encoding="utf-8")

    manifest = build_bundle_manifest(recommendation)
    manifest_path = target_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _resolve_bundle_path(output_dir: Path, relative_path: str) -> Path:
    """Resolve a generated file path without allowing path traversal."""
    target_path = (output_dir / relative_path).resolve()
    root = output_dir.resolve()

    if target_path == root or root not in target_path.parents:
        raise ValueError(
            f"Generated file path escapes bundle directory: {relative_path}"
        )

    return target_path
