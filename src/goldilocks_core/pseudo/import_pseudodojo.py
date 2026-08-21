from __future__ import annotations

import hashlib
import json
import re
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pymatgen.core.libxcfunc import LibxcFunc
from pymatgen.core.xcfunc import XcFunc

from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.validation import (
    PseudoImportError,
    finite_positive_cutoff,
    required_functional,
)

HARTREE_TO_RYDBERG = 2.0
_MD5 = re.compile(r"[0-9a-fA-F]{32}")
_LICENCE_NOTICE = """\
PseudoDojo pseudopotentials are distributed under the Creative Commons
Attribution 4.0 International licence (CC BY 4.0).

Licence: https://creativecommons.org/licenses/by/4.0/
Source: https://www.pseudo-dojo.org/
"""


def preparer(table: PseudoTable):
    if table.provider != "pseudodojo":
        raise ValueError(f"not a PseudoDojo table: {table.id}")

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        try:
            reports = _reports(sources["metadata"])
            entries = _extract_pseudos(
                sources["pseudopotentials"], destination, table, reports
            )
            write_table_manifest(destination, table, entries)
            (destination / "LICENSE.txt").write_text(_LICENCE_NOTICE, encoding="utf-8")
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
                f"cannot normalize PseudoDojo table {table.id}: {error}"
            ) from error

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
                raise PseudoImportError(f"cannot extract {member.name}")
            report = json.load(source)
            if not isinstance(report, dict):
                raise PseudoImportError(
                    f"dojo report for {element} must be a JSON object"
                )
            digest = report.get("md5_upf")
            if not isinstance(digest, str) or _MD5.fullmatch(digest) is None:
                raise PseudoImportError(
                    f"dojo report for {element} has invalid md5_upf"
                )
            functional = _report_functional(
                report.get("xc"), f"dojo report XC for {element}"
            )
            hints = report.get("hints")
            if not isinstance(hints, dict):
                raise PseudoImportError(f"dojo report for {element} lacks cutoff hints")
            cutoff_hints: dict[str, float] = {}
            for level in ("low", "normal", "high"):
                values = hints.get(level)
                if not isinstance(values, dict) or "ecut" not in values:
                    raise PseudoImportError(
                        f"dojo report for {element} lacks {level} cutoff hint"
                    )
                cutoff_hints[level] = (
                    finite_positive_cutoff(
                        values["ecut"], f"dojo {element} {level} ecut"
                    )
                    * HARTREE_TO_RYDBERG
                )
            if element in reports:
                raise PseudoImportError(f"duplicate dojo report for {element}")
            reports[element] = {
                "md5": digest.lower(),
                "functional": functional,
                "cutoff_hints": cutoff_hints,
            }
    if not reports:
        raise PseudoImportError("no dojo reports found")
    return reports


def _report_functional(value: object, label: str) -> str:
    if isinstance(value, str):
        return required_functional(value, label)
    if (
        not isinstance(value, Mapping)
        or value.get("@class") != "XcFunc"
        or value.get("@module") != "pymatgen.core.xcfunc"
    ):
        raise PseudoImportError(f"{label} must be a name or serialized Pymatgen XcFunc")

    xc = _libxc_component(value.get("xc"), label)
    x = _libxc_component(value.get("x"), label)
    c = _libxc_component(value.get("c"), label)
    try:
        decoded = XcFunc(xc=xc, x=x, c=c)
    except ValueError as error:
        raise PseudoImportError(f"{label} is not a complete XcFunc") from error
    return required_functional(decoded.name, label)


def _libxc_component(value: object, label: str) -> LibxcFunc | None:
    if value is None:
        return None
    if (
        not isinstance(value, Mapping)
        or value.get("@class") != "LibxcFunc"
        or value.get("@module") != "pymatgen.core.libxcfunc"
        or not isinstance(value.get("name"), str)
    ):
        raise PseudoImportError(f"{label} has an invalid LibXC component")
    try:
        return LibxcFunc[value["name"]]
    except KeyError as error:
        raise PseudoImportError(
            f"{label} names unknown LibXC component {value['name']!r}"
        ) from error


def _extract_pseudos(
    archive: Path,
    destination: Path,
    table: PseudoTable,
    reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if table.charge_density_dual is None:
        raise PseudoImportError(
            f"PseudoDojo table {table.id} has no charge-density dual"
        )
    seen: set[str] = set()
    pseudos = destination / "pseudos"
    pseudos.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".upf"):
                continue
            element = Path(member.name).stem
            if element in seen:
                raise PseudoImportError(f"duplicate UPF for {element}")
            report = reports.get(element)
            if report is None:
                raise PseudoImportError(f"{element}.upf has no dojo report")
            if report["functional"] != table.functional:
                raise PseudoImportError(
                    f"{element}: report functional {report['functional']} does not "
                    f"match table functional {table.functional}"
                )
            source = tar.extractfile(member)
            if source is None:
                raise PseudoImportError(f"cannot extract {member.name}")
            target = pseudos / f"{element}.upf"
            digest = hashlib.md5()
            with target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest().lower() != report["md5"]:
                raise PseudoImportError(f"{element}.upf does not match md5_upf")

            parsed = parse_upf_metadata(target)
            if parsed.element != element:
                raise PseudoImportError(
                    f"{element}: UPF element is {parsed.element or 'unknown'}"
                )
            upf_functional = required_functional(
                parsed.functional, f"UPF functional for {element}"
            )
            if upf_functional != table.functional:
                raise PseudoImportError(
                    f"{element}: UPF functional {upf_functional} does not match "
                    f"table functional {table.functional}"
                )
            if parsed.relativistic != table.relativistic and not (
                table.relativistic == "scalar"
                and parsed.relativistic == "non-relativistic"
            ):
                raise PseudoImportError(
                    f"{element}: UPF relativistic treatment "
                    f"{parsed.relativistic or 'unknown'} does not match table "
                    f"treatment {table.relativistic}"
                )

            cutoff_hints = report["cutoff_hints"]
            high = cutoff_hints["high"]
            entries.append(
                {
                    "element": element,
                    "path": target.relative_to(destination).as_posix(),
                    "md5": digest.hexdigest(),
                    "header_format": parsed.header_format,
                    "upf_relativistic": parsed.relativistic,
                    "pseudo_type": parsed.pseudo_type,
                    "z_valence": parsed.z_valence,
                    "ecutwfc_ry": high,
                    "ecutrho_ry": finite_positive_cutoff(
                        high * table.charge_density_dual,
                        f"dojo {element} charge-density cutoff",
                    ),
                    "cutoff_hints": cutoff_hints,
                    "source_identifier": member.name,
                    "frozen_4f_core": "3plus" in table.upstream_table,
                }
            )
            seen.add(element)

    missing_reports = set(reports) - seen
    if missing_reports:
        raise PseudoImportError(
            "dojo reports describe absent UPFs: " + ", ".join(sorted(missing_reports))
        )
    return entries
