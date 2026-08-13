"""Normalize verified PseudoDojo source archives into an installed table."""

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

HARTREE_TO_RYDBERG = 2.0
DEFAULT_DUAL = 4.0


class TableIncomplete(RuntimeError):
    """Provider archives disagree or omit required scientific metadata."""


def preparer(table: PseudoTable):
    """Return an asset preparer bound to one PseudoDojo table declaration."""
    if table.provider != "pseudodojo":
        raise ValueError(f"not a PseudoDojo table: {table.id}")

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        reports = _reports(sources["metadata"])
        entries = _extract_pseudos(
            sources["pseudopotentials"], destination, table, reports
        )
        write_table_manifest(destination, table, entries)

    return prepare


def _reports(archive: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".djrepo"):
                continue
            element = Path(member.name).stem
            source = tar.extractfile(member)
            if source is None:
                continue
            report = json.load(source)
            digest = report.get("md5_upf")
            hints = report.get("hints")
            if not digest:
                raise TableIncomplete(f"dojo report for {element} has no md5_upf")
            if not isinstance(hints, dict) or not all(
                isinstance(hints.get(level), dict)
                and hints[level].get("ecut") is not None
                for level in ("low", "normal", "high")
            ):
                raise TableIncomplete(
                    f"dojo report for {element} lacks low/normal/high cutoff hints"
                )
            if element in reports:
                raise TableIncomplete(f"duplicate dojo report for {element}")
            reports[element] = {"md5": digest, "hints": hints}
    if not reports:
        raise TableIncomplete("no dojo reports found")
    return reports


def _extract_pseudos(
    archive: Path,
    destination: Path,
    table: PseudoTable,
    reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    pseudos = destination / "pseudos"
    pseudos.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".upf"):
                continue
            element = Path(member.name).stem
            if element in seen:
                raise TableIncomplete(f"duplicate UPF for {element}")
            report = reports.get(element)
            if report is None:
                raise TableIncomplete(f"{element}.upf has no dojo report")
            source = tar.extractfile(member)
            if source is None:
                raise TableIncomplete(f"cannot extract {member.name}")
            target = pseudos / f"{element}.upf"
            digest = hashlib.md5()
            with target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest().lower() != report["md5"].lower():
                raise TableIncomplete(f"{element}.upf does not match md5_upf")
            parsed = parse_upf_metadata(target)
            cutoff_hints = {
                level: float(values["ecut"]) * HARTREE_TO_RYDBERG
                for level, values in report["hints"].items()
                if isinstance(values, dict) and values.get("ecut") is not None
            }
            high = cutoff_hints["high"]
            entries.append(
                {
                    "element": element,
                    "path": target.relative_to(destination).as_posix(),
                    "md5": digest.hexdigest(),
                    "header_format": parsed.header_format,
                    "pseudo_type": parsed.pseudo_type,
                    "z_valence": parsed.z_valence,
                    "ecutwfc_ry": high,
                    "ecutrho_ry": high * DEFAULT_DUAL,
                    "cutoff_hints": cutoff_hints,
                    "f_in_core": "3plus" in table.upstream_table,
                }
            )
            seen.add(element)
    missing = set(reports) - seen
    if missing:
        raise TableIncomplete(
            "dojo reports describe absent UPFs: " + ", ".join(sorted(missing))
        )
    return entries
