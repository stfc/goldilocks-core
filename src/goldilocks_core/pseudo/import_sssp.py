from __future__ import annotations

import json
import re
import shutil
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from goldilocks_core.pseudo.installed import (
    archive_files,
    extract_upf,
    write_table_manifest,
)
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.validation import (
    PseudoImportError,
    finite_positive_cutoff,
    required_functional,
)

_MD5 = re.compile(r"[0-9a-fA-F]{32}")


def preparer(table: PseudoTable):
    if table.provider != "sssp":
        raise ValueError(f"not an SSSP table: {table.id}")

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        try:
            metadata = json.loads(sources["metadata"].read_text(encoding="utf-8"))
            if not isinstance(metadata, dict) or not metadata:
                raise PseudoImportError("SSSP metadata must be a non-empty object")
            entries = _extract_pseudos(
                sources["pseudopotentials"], destination, metadata, table
            )
            write_table_manifest(destination, table, entries)
            shutil.copyfile(sources["licence"], destination / "LICENSE.txt")
        except PseudoImportError:
            raise
        except (
            KeyError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            tarfile.TarError,
        ) as error:
            raise PseudoImportError(
                f"cannot normalize SSSP table {table.id}: {error}"
            ) from error

    return prepare


def _metadata_by_filename(
    metadata: dict[str, dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any]]]:
    by_filename: dict[str, tuple[str, dict[str, Any]]] = {}
    for element, facts in metadata.items():
        if not isinstance(element, str) or not isinstance(facts, dict):
            raise PseudoImportError("SSSP metadata entries must be element objects")
        filename = facts.get("filename")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
        ):
            raise PseudoImportError(f"SSSP entry for {element} has an unsafe filename")
        if filename in by_filename:
            raise PseudoImportError(f"duplicate SSSP filename {filename}")
        digest = facts.get("md5")
        if not isinstance(digest, str) or _MD5.fullmatch(digest) is None:
            raise PseudoImportError(f"SSSP entry for {element} has invalid md5")
        by_filename[filename] = (element, facts)
    return by_filename


def _extract_pseudos(
    archive: Path,
    destination: Path,
    metadata: dict[str, dict[str, Any]],
    table: PseudoTable,
) -> list[dict[str, Any]]:
    by_filename = _metadata_by_filename(metadata)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    pseudos = destination / "pseudos"
    pseudos.mkdir()
    for name, source in archive_files(archive):
        filename = Path(name).name
        expected = by_filename.get(filename)
        if expected is None:
            raise PseudoImportError(f"{filename} has no SSSP metadata entry")
        element, facts = expected
        if element in seen:
            raise PseudoImportError(f"duplicate SSSP entry for {element}")
        entry = extract_upf(
            source,
            pseudos / filename,
            element,
            table,
            facts["md5"],
            f"{filename} does not match SSSP md5",
        )
        if facts.get("element") not in {None, element}:
            raise PseudoImportError(
                f"{element}: SSSP sidecar element is {facts['element']!r}"
            )
        if "functional" in facts:
            sidecar_functional = required_functional(
                facts["functional"], f"SSSP functional for {element}"
            )
            if sidecar_functional != table.functional:
                raise PseudoImportError(
                    f"{element}: SSSP functional {sidecar_functional} does not "
                    f"match table functional {table.functional}"
                )
        entry.update(
            ecutwfc_ry=finite_positive_cutoff(
                facts.get("cutoff_wfc"), f"SSSP {element} cutoff_wfc"
            ),
            ecutrho_ry=finite_positive_cutoff(
                facts.get("cutoff_rho"), f"SSSP {element} cutoff_rho"
            ),
            source_identifier=facts.get("pseudopotential"),
            frozen_4f_core=False,
        )
        entries.append(entry)
        seen.add(element)

    missing = set(metadata) - seen
    if missing:
        raise PseudoImportError(
            "SSSP metadata describes absent UPFs: " + ", ".join(sorted(missing))
        )
    return entries
