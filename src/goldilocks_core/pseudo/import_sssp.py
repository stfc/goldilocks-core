"""Normalize verified SSSP source files into an installed table."""

from __future__ import annotations

import hashlib
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.registry import PseudoTable


class TableIncomplete(RuntimeError):
    """The SSSP archive and its metadata do not form one complete table."""


def preparer(table: PseudoTable):
    """Return an asset preparer bound to one SSSP table declaration."""
    if table.provider != "sssp":
        raise ValueError(f"not an SSSP table: {table.id}")

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        metadata = json.loads(sources["metadata"].read_text())
        entries = _extract_pseudos(sources["pseudopotentials"], destination, metadata)
        write_table_manifest(destination, table, entries)

    return prepare


def _extract_pseudos(
    archive: Path,
    destination: Path,
    metadata: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_filename = {
        entry["filename"]: (element, entry) for element, entry in metadata.items()
    }
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    pseudos = destination / "pseudos"
    pseudos.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            filename = Path(member.name).name
            expected = by_filename.get(filename)
            if expected is None:
                raise TableIncomplete(f"{filename} has no SSSP metadata entry")
            element, facts = expected
            if element in seen:
                raise TableIncomplete(f"duplicate SSSP entry for {element}")
            source = tar.extractfile(member)
            if source is None:
                raise TableIncomplete(f"cannot extract {member.name}")
            target = pseudos / filename
            digest = hashlib.md5()
            with target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest().lower() != facts["md5"].lower():
                raise TableIncomplete(f"{filename} does not match SSSP md5")
            parsed = parse_upf_metadata(target)
            ecutwfc = _positive_cutoff(facts, "cutoff_wfc")
            ecutrho = _positive_cutoff(facts, "cutoff_rho")
            entries.append(
                {
                    "element": element,
                    "path": target.relative_to(destination).as_posix(),
                    "md5": digest.hexdigest(),
                    "header_format": parsed.header_format,
                    "pseudo_type": parsed.pseudo_type,
                    "z_valence": parsed.z_valence,
                    "ecutwfc_ry": ecutwfc,
                    "ecutrho_ry": ecutrho,
                    "source_pseudopotential": facts.get("pseudopotential"),
                    "f_in_core": False,
                }
            )
            seen.add(element)
    missing = set(metadata) - seen
    if missing:
        raise TableIncomplete(
            "SSSP metadata describes absent UPFs: " + ", ".join(sorted(missing))
        )
    return entries


def _positive_cutoff(facts: dict[str, Any], key: str) -> float:
    try:
        value = float(facts[key])
    except (KeyError, TypeError, ValueError) as error:
        raise TableIncomplete(f"SSSP entry lacks numeric {key}") from error
    if value <= 0:
        raise TableIncomplete(f"SSSP entry has non-positive {key}")
    return value
