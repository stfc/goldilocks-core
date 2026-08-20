from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from goldilocks_core.contracts import PseudoCutoffs, PseudoMetadata
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.validation import (
    AmbiguousCutoffMetadata,
    PseudoImportError,
    finite_positive_cutoff,
    required_functional,
)

_HARTREE_TO_RYDBERG = 2.0


@dataclass(frozen=True, slots=True)
class _DiscoveredCutoffs:
    provider: str
    source_identifier: str | None
    cutoffs: PseudoCutoffs


def load_pseudo_metadata(root: str | Path) -> list[PseudoMetadata]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"pseudopotential root is not a directory: {root}")
    upf_files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".upf"
    )
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
        metadata.append(item)
    return metadata


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
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=high,
        ),
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
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=finite_positive_cutoff(
                entry.get("ecutwfc_ry", entry.get("cutoff_wfc")),
                f"{sidecar.name} cutoff_wfc",
            ),
            ecutrho_ry=finite_positive_cutoff(
                entry.get("ecutrho_ry", entry.get("cutoff_rho")),
                f"{sidecar.name} cutoff_rho",
            ),
        ),
    )


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
