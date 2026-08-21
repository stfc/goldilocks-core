from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
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


def _extract_pseudos(
    archive: Path,
    destination: Path,
    metadata: dict[str, dict[str, Any]],
    table: PseudoTable,
) -> list[dict[str, Any]]:
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
                raise PseudoImportError(f"{filename} has no SSSP metadata entry")
            element, facts = expected
            if element in seen:
                raise PseudoImportError(f"duplicate SSSP entry for {element}")
            source = tar.extractfile(member)
            if source is None:
                raise PseudoImportError(f"cannot extract {member.name}")
            target = pseudos / filename
            digest = hashlib.md5()
            with target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest().lower() != facts["md5"].lower():
                raise PseudoImportError(f"{filename} does not match SSSP md5")

            parsed = parse_upf_metadata(target)
            if parsed.element != element:
                raise PseudoImportError(
                    f"{element}: UPF element is {parsed.element or 'unknown'}"
                )
            if facts.get("element") not in {None, element}:
                raise PseudoImportError(
                    f"{element}: SSSP sidecar element is {facts['element']!r}"
                )
            upf_functional = required_functional(
                parsed.functional, f"UPF functional for {element}"
            )
            if upf_functional != table.functional:
                raise PseudoImportError(
                    f"{element}: UPF functional {upf_functional} does not match "
                    f"table functional {table.functional}"
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
            if parsed.relativistic != table.relativistic and not (
                table.relativistic == "scalar"
                and parsed.relativistic == "non-relativistic"
            ):
                raise PseudoImportError(
                    f"{element}: UPF relativistic treatment "
                    f"{parsed.relativistic or 'unknown'} does not match table "
                    f"treatment {table.relativistic}"
                )

            entries.append(
                {
                    "element": element,
                    "path": target.relative_to(destination).as_posix(),
                    "md5": digest.hexdigest(),
                    "header_format": parsed.header_format,
                    "upf_relativistic": parsed.relativistic,
                    "pseudo_type": parsed.pseudo_type,
                    "z_valence": parsed.z_valence,
                    "ecutwfc_ry": finite_positive_cutoff(
                        facts.get("cutoff_wfc"), f"SSSP {element} cutoff_wfc"
                    ),
                    "ecutrho_ry": finite_positive_cutoff(
                        facts.get("cutoff_rho"), f"SSSP {element} cutoff_rho"
                    ),
                    "source_identifier": facts.get("pseudopotential"),
                    "frozen_4f_core": False,
                }
            )
            seen.add(element)

    missing = set(metadata) - seen
    if missing:
        raise PseudoImportError(
            "SSSP metadata describes absent UPFs: " + ", ".join(sorted(missing))
        )
    return entries
