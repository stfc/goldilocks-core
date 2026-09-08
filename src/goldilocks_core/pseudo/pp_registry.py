from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.validation import (
    AmbiguousCutoffMetadata,
    PseudoImportError,
    finite_positive_cutoff,
    required_functional,
)

_HARTREE_TO_RYDBERG = 2.0
_PUBLICATION_SIDECAR = "goldilocks-pseudopotentials.json"


@dataclass(frozen=True, slots=True)
class _DiscoveredCutoffs:
    provider: str
    source_identifier: str | None
    cutoffs: dict[str, float | None]


def load_pseudo_metadata(root: str | Path) -> list[PseudoMetadata]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"pseudopotential root is not a directory: {root}")
    upf_files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".upf"
    )
    publication_metadata = _load_publication_metadata(root)
    metadata: list[PseudoMetadata] = []
    for upf in upf_files:
        item = parse_upf_metadata(upf)
        discovered = _discover_cutoffs(upf, root, item)
        if discovered is None:
            subject = item.element or item.filename
            item = replace(
                item,
                warnings=(
                    f"No recognized cutoff metadata found for {subject} under "
                    f"custom pseudopotential root {root}.",
                ),
            )
        else:
            item = replace(
                item,
                provider=discovered.provider,
                source_identifier=discovered.source_identifier,
                cutoffs=discovered.cutoffs,
            )
        if publication_metadata:
            item = replace(
                item,
                pseudo_info={**item.pseudo_info, **publication_metadata},
            )
        metadata.append(item)
    return metadata


def _load_publication_metadata(root: Path) -> dict[str, str]:
    sidecar = root / _PUBLICATION_SIDECAR
    if not sidecar.exists():
        return {}
    if sidecar.is_symlink() or not sidecar.is_file():
        raise PseudoImportError(
            f"pseudopotential publication sidecar must be a regular file: {sidecar}"
        )
    try:
        document = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PseudoImportError(
            f"invalid pseudopotential publication sidecar {sidecar}"
        ) from error
    required = {
        "schema_version",
        "licence",
        "licence_file",
        "citation",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise PseudoImportError(
            f"pseudopotential publication sidecar fields are invalid: {sidecar}"
        )
    if isinstance(document["schema_version"], bool) or document["schema_version"] != 1:
        raise PseudoImportError(
            f"unsupported pseudopotential publication sidecar schema: {sidecar}"
        )
    for field in ("licence", "licence_file", "citation"):
        value = document[field]
        if not isinstance(value, str) or not value.strip():
            raise PseudoImportError(
                f"pseudopotential publication sidecar {field} must be non-empty: "
                f"{sidecar}"
            )

    relative = document["licence_file"]
    candidate = PurePosixPath(relative)
    if (
        "\\" in relative
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or candidate.as_posix() != relative
    ):
        raise PseudoImportError(
            f"pseudopotential publication licence_file must be contained: {sidecar}"
        )
    licence_file = root.joinpath(*candidate.parts)
    try:
        resolved_licence = licence_file.resolve(strict=True)
        resolved_licence.relative_to(root)
        licence_text = resolved_licence.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        raise PseudoImportError(
            f"cannot read contained pseudopotential licence_file {licence_file}"
        ) from error
    if not licence_text:
        raise PseudoImportError(
            f"pseudopotential publication licence_file is empty: {licence_file}"
        )
    return {
        "licence": document["licence"],
        "licence_text": licence_text,
        "citation": document["citation"],
    }


def _discover_cutoffs(
    upf: Path,
    root: Path,
    metadata: PseudoMetadata,
) -> _DiscoveredCutoffs | None:
    matches: list[_DiscoveredCutoffs] = []
    dojo = upf.with_suffix(".djrepo")
    if dojo.is_file():
        matches.append(_load_dojo_sidecar(dojo, upf, metadata))

    json_candidates = set(upf.parent.glob("*.json"))
    if upf.parent != root:
        json_candidates.add(upf.parent.parent / f"{upf.parent.name}.json")
    for candidate in sorted(json_candidates):
        if candidate.is_file():
            match = _load_sssp_sidecar(candidate, upf, metadata)
            if match is not None:
                matches.append(match)

    if len(matches) > 1:
        raise AmbiguousCutoffMetadata(f"{upf.name} matches multiple cutoff records")
    return matches[0] if matches else None


def _load_dojo_sidecar(
    sidecar: Path,
    upf: Path,
    metadata: PseudoMetadata,
) -> _DiscoveredCutoffs:
    try:
        report = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PseudoImportError(f"invalid PseudoDojo sidecar {sidecar}") from error
    if not isinstance(report, dict):
        raise PseudoImportError(f"PseudoDojo sidecar must be an object: {sidecar}")
    if report.get("md5_upf") != _md5(upf):
        raise PseudoImportError(f"PseudoDojo sidecar does not match {upf.name}")
    sidecar_functional = required_functional(
        report.get("xc"), f"PseudoDojo XC in {sidecar}"
    )
    upf_functional = required_functional(
        metadata.functional, f"UPF functional in {upf}"
    )
    if sidecar_functional != upf_functional:
        raise PseudoImportError(
            f"{upf.name} functional {upf_functional} disagrees with "
            f"{sidecar.name} functional {sidecar_functional}"
        )
    hints = report.get("hints")
    if not isinstance(hints, dict):
        raise PseudoImportError(f"PseudoDojo sidecar lacks hints: {sidecar}")
    values: list[tuple[str, float]] = []
    for level in ("low", "normal", "high"):
        hint = hints.get(level)
        if not isinstance(hint, dict) or "ecut" not in hint:
            raise PseudoImportError(f"PseudoDojo sidecar lacks {level} ecut: {sidecar}")
        values.append(
            (
                level,
                finite_positive_cutoff(hint["ecut"], f"{sidecar.name} {level} ecut")
                * _HARTREE_TO_RYDBERG,
            )
        )
    high = dict(values)["high"]
    return _DiscoveredCutoffs(
        provider="pseudodojo",
        source_identifier=sidecar.name,
        cutoffs={"ecutwfc_ry": high, "ecutrho_ry": None},
    )


def _load_sssp_sidecar(
    sidecar: Path,
    upf: Path,
    metadata: PseudoMetadata,
) -> _DiscoveredCutoffs | None:
    try:
        document = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or metadata.element is None:
        return None
    entry = document.get(metadata.element)
    if not isinstance(entry, dict) or entry.get("filename") != upf.name:
        return None
    if "md5" in entry and entry["md5"] != _md5(upf):
        raise PseudoImportError(f"SSSP sidecar does not match {upf.name}")
    if "functional" in entry:
        sidecar_functional = required_functional(
            entry["functional"], f"SSSP functional in {sidecar}"
        )
        upf_functional = required_functional(
            metadata.functional, f"UPF functional in {upf}"
        )
        if sidecar_functional != upf_functional:
            raise PseudoImportError(
                f"{upf.name} functional {upf_functional} disagrees with "
                f"{sidecar.name} functional {sidecar_functional}"
            )
    return _DiscoveredCutoffs(
        provider="sssp",
        source_identifier=entry.get("pseudopotential"),
        cutoffs={
            "ecutwfc_ry": finite_positive_cutoff(
                entry.get("ecutwfc_ry", entry.get("cutoff_wfc")),
                f"{sidecar.name} cutoff_wfc",
            ),
            "ecutrho_ry": finite_positive_cutoff(
                entry.get("ecutrho_ry", entry.get("cutoff_rho")),
                f"{sidecar.name} cutoff_rho",
            ),
        },
    )


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
