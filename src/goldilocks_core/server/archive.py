from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from goldilocks_core.contracts import JsonDict, Result
from goldilocks_core.pseudo.registry import PseudoTable

ARCHIVE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorkbenchArchive:
    source_name: str
    source_content: str
    canonical_cif: str
    review: JsonDict
    result: Result
    table: PseudoTable
    licence_path: Path


def build_workbench_archive(material: WorkbenchArchive) -> bytes:
    files: dict[str, bytes] = {}
    _add(files, f"source/{material.source_name}", material.source_content.encode())
    _add(files, "structure/canonical.cif", material.canonical_cif.encode())
    for generated in material.result.generated_files:
        _add(files, generated.path, generated.content.encode())
    for pseudo in material.result.selection.pseudopotentials:
        if pseudo.filepath is None or pseudo.filename is None:
            raise ValueError(
                f"Cannot archive unresolved pseudopotential for {pseudo.element}."
            )
        _add(
            files,
            f"pseudopotentials/{pseudo.filename}",
            Path(pseudo.filepath).read_bytes(),
        )

    licence_name = f"licences/{material.table.id}.txt"
    _add(files, licence_name, material.licence_path.read_bytes())
    _add(files, "CITATIONS.md", _citations(material).encode())
    _add(files, "README.md", _readme(material, licence_name).encode())

    review = material.review
    manifest = {
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "goldilocks_core_version": version("goldilocks-core"),
        "review_digest": review["review_digest"],
        "source": review["structure"]["source"],
        "canonical_structure": {
            "path": "structure/canonical.cif",
            "sha256": _sha256(files["structure/canonical.cif"]),
        },
        "intent": review["intent"],
        "hints": review["hints"],
        "records": review["records"],
        "selection": review["selection"],
        "generated_files": review["generated_files"],
        "warnings": review["warnings"],
        "citations": [material.table.citation],
        "archive_files": {
            path: {"sha256": _sha256(payload), "size_bytes": len(payload)}
            for path, payload in sorted(files.items())
        },
    }
    _add(
        files,
        "goldilocks.json",
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    )
    checksums = "".join(
        f"{_sha256(payload)}  {path}\n" for path, payload in sorted(files.items())
    )
    _add(files, "checksums.sha256", checksums.encode())

    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for path, payload in sorted(files.items()):
            info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    return output.getvalue()


def _add(files: dict[str, bytes], path: str, payload: bytes) -> None:
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"Unsafe archive path: {path!r}.")
    normalized = candidate.as_posix()
    if normalized in files:
        raise ValueError(f"Duplicate archive path: {normalized!r}.")
    files[normalized] = payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _citations(material: WorkbenchArchive) -> str:
    return (
        "# Citations\n\n"
        "Goldilocks records scientific provenance in `goldilocks.json`. "
        "Cite the selected pseudopotential source when publishing results.\n\n"
        f"- {material.table.citation}\n"
    )


def _readme(material: WorkbenchArchive, licence_name: str) -> str:
    return (
        "# Goldilocks calculation archive\n\n"
        "This archive was assembled by the server from a fresh Core computation.\n\n"
        f"- Original uploaded structure: `source/{material.source_name}`\n"
        "- Canonical structure: `structure/canonical.cif`\n"
        "- Calculation inputs: `inputs/`\n"
        "- Selected pseudopotentials: `pseudopotentials/`\n"
        f"- Pseudopotential licence material: `{licence_name}`\n"
        "- Machine-readable provenance: `goldilocks.json`\n"
        "- Independent file hashes: `checksums.sha256`\n"
    )
