"""SSSP / PseudoDojo provider normalization: tarball -> installed UPF table.

Ported near-verbatim from v1's ``pseudo/installed.py``, ``pseudo/import_pseudodojo.py``,
``pseudo/import_sssp.py``, ``pseudo/validation.py``, and ``pseudo/install.py`` (v2
epic 3, #4) -- five files merged into one because they are all steps of the same
pipeline (extract a provider's tarball, verify it against its own sidecar
metadata, write the installed-table manifest, wire the result up as an
``AssetInstallation``), matching ``assets/pseudopotentials/``'s target layout
(goldilocks-core-design.md S8).

One correctness fix made while porting: PseudoDojo's ``frozen_4f_core`` is read
from ``table.frozen_4f_core`` (a declared registry field, ``registry.py``) rather
than re-derived here by substring-matching ``table.upstream_table`` for
``"3plus"`` -- see ``registry.py``'s docstring for why.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tarfile
from collections.abc import Callable, Iterator, Mapping
from numbers import Real
from pathlib import Path
from typing import Any, BinaryIO

from pymatgen.core.libxcfunc import LibxcFunc
from pymatgen.core.xcfunc import XcFunc

from goldilocks_core.assets.pseudopotentials.registry import (
    InvalidPseudoRegistry,
    PseudoTable,
    load_tables,
)
from goldilocks_core.assets.pseudopotentials.upf import (
    PseudoCutoffs,
    PseudoMetadata,
    parse_upf_metadata,
)
from goldilocks_core.assets.records import (
    AssetInstallation,
    AssetPreparer,
    InstalledAsset,
)
from goldilocks_core.assets.store import AssetCorrupt
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.types import PathLike

# --- shared validators (v1 pseudo/validation.py) ---------------------------


class PseudoImportError(ExpectedFailure, ValueError):
    kind = "pseudo_import_error"
    category = "local"


def finite_positive_cutoff(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise PseudoImportError(f"{label} must be finite and positive; got {value!r}")
    return float(value)


def required_functional(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise PseudoImportError(f"{label} must name a functional; got {value!r}")
    functional = normalize_functional_label(value)
    if functional is None:
        raise PseudoImportError(f"{label} must name a functional; got {value!r}")
    return functional


# --- extraction + manifest (v1 pseudo/installed.py) -------------------------

TABLE_MANIFEST = "pseudo-table.json"
TABLE_LICENCE = "LICENSE.txt"
"""The installed table's licence material, which every preparer writes: the
provider's licence file for SSSP, the CC BY 4.0 notice for PseudoDojo. A
bundle ships it beside the table's UPFs (``service._pseudo.pseudo_artifacts``,
#157)."""
_SCHEMA_VERSION = 2
_RELATIVISTIC = frozenset({"scalar", "full", "non-relativistic"})
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "id",
    "version",
    "provider",
    "functional",
    "accuracy",
    "relativistic",
    "licence",
    "citation",
    "entries",
}
_ENTRY_FIELDS = {
    "element",
    "path",
    "md5",
    "header_format",
    "pseudo_type",
    "z_valence",
    "ecutwfc_ry",
    "ecutrho_ry",
    "source_identifier",
    "frozen_4f_core",
}
_OPTIONAL_ENTRY_FIELDS = {"cutoff_hints", "upf_relativistic"}


def write_table_manifest(
    destination: Path,
    table: PseudoTable,
    entries: list[dict[str, Any]],
) -> None:
    elements = [entry.get("element") for entry in entries]
    expected = set(table.elements)
    if len(elements) != len(set(elements)):
        raise ValueError("pseudopotential table entries must have unique elements")
    if set(elements) != expected:
        missing = ", ".join(sorted(expected - set(elements))) or "none"
        extra = (
            ", ".join(sorted(str(element) for element in set(elements) - expected))
            or "none"
        )
        raise ValueError(f"table coverage mismatch; missing: {missing}; extra: {extra}")
    for entry in entries:
        _validate_entry_shape(entry)

    document = {
        "schema_version": _SCHEMA_VERSION,
        "id": table.asset.id,
        "version": table.version,
        "provider": table.provider,
        "functional": table.functional,
        "accuracy": table.accuracy,
        "relativistic": table.relativistic,
        "licence": table.licence,
        "citation": table.citation,
        "entries": sorted(entries, key=lambda entry: entry["element"]),
    }
    (destination / TABLE_MANIFEST).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def archive_files(archive: Path, suffix: str = "") -> Iterator[tuple[str, BinaryIO]]:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.lower().endswith(suffix):
                continue
            source = tar.extractfile(member)
            if source is None:
                raise PseudoImportError(f"cannot extract {member.name}")
            with source:
                yield member.name, source


def extract_upf(
    source: BinaryIO,
    target: Path,
    element: str,
    table: PseudoTable,
    md5: str,
    mismatch: str,
) -> dict[str, Any]:
    digest = hashlib.md5()
    with target.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != md5.lower():
        raise PseudoImportError(mismatch)
    parsed = parse_upf_metadata(target)
    if parsed.element != element:
        raise PseudoImportError(
            f"{element}: UPF element is {parsed.element or 'unknown'}"
        )
    functional = required_functional(parsed.functional, f"UPF functional for {element}")
    if functional != table.functional:
        raise PseudoImportError(
            f"{element}: UPF functional {functional} does not match "
            f"table functional {table.functional}"
        )
    if parsed.relativistic != table.relativistic and not (
        table.relativistic == "scalar" and parsed.relativistic == "non-relativistic"
    ):
        raise PseudoImportError(
            f"{element}: UPF relativistic treatment "
            f"{parsed.relativistic or 'unknown'} does not match table "
            f"treatment {table.relativistic}"
        )
    return {
        "element": element,
        "path": f"pseudos/{target.name}",
        "md5": digest.hexdigest(),
        "header_format": parsed.header_format,
        "upf_relativistic": parsed.relativistic,
        "pseudo_type": parsed.pseudo_type,
        "z_valence": parsed.z_valence,
    }


def _validate_manifest(
    data: Any,
    installed: InstalledAsset,
    table: PseudoTable | None,
) -> None:
    if not isinstance(data, dict) or set(data) != _TOP_LEVEL_FIELDS:
        raise ValueError("pseudopotential manifest fields are invalid")
    if (
        isinstance(data["schema_version"], bool)
        or data["schema_version"] != _SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported pseudopotential manifest schema_version "
            f"{data['schema_version']!r}"
        )
    if data["id"] != installed.id or data["version"] != installed.version:
        raise ValueError("pseudopotential manifest identity does not match asset")
    for field in ("provider", "licence", "citation"):
        data[field] = _nonempty_string(data[field], field)
    data["functional"] = required_functional(data["functional"], "table functional")
    for field, allowed, label in (
        ("accuracy", {"efficiency", "precision"}, "accuracy"),
        ("relativistic", _RELATIVISTIC, "relativistic treatment"),
    ):
        if data[field] not in allowed:
            raise ValueError(f"unsupported table {label} {data[field]!r}")
    if not isinstance(data["entries"], list) or not data["entries"]:
        raise ValueError("pseudopotential manifest entries must be non-empty")
    if table is not None:
        declared = {
            field: getattr(table, field)
            for field in (
                "version",
                "provider",
                "functional",
                "accuracy",
                "relativistic",
                "licence",
                "citation",
            )
        }
        declared["id"] = table.asset.id
        if declared != {field: data[field] for field in declared}:
            raise ValueError(
                "pseudopotential manifest disagrees with registry declaration"
            )


def load_installed_table(
    installed: InstalledAsset,
    *,
    table: PseudoTable | None = None,
) -> tuple[PseudoMetadata, ...]:
    """One ``PseudoMetadata`` per entry of the installed table's manifest,
    each UPF's md5 checked against it. ``asset_path`` is the entry's path
    inside the installation, and ``content_sha256``/``content_size_bytes``
    come from ``installed``'s verified inventory (#177). ``cutoffs`` and
    ``cutoff_hints`` are what the provider publishes (``_published_cutoffs``,
    #180). Raises ``AssetCorrupt`` for a manifest or file that does not
    check out."""
    try:
        manifest_path = installed.path(TABLE_MANIFEST)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(data, installed, table)
        inventory = {file.path: file for file in installed.files}
        metadata: list[PseudoMetadata] = []
        elements: list[str] = []
        paths: list[str] = []
        for entry in data["entries"]:
            _validate_entry_shape(entry)
            element = _nonempty_string(entry["element"], "entry element")
            relative_path = _nonempty_string(entry["path"], "entry path")
            path = installed.path(relative_path)
            if _md5(path) != entry["md5"].lower():
                raise ValueError(f"entry md5 does not match {relative_path}")
            entry_relativistic = entry.get("upf_relativistic", data["relativistic"])
            verified = inventory[relative_path]
            metadata.append(
                PseudoMetadata(
                    filepath=str(path),
                    filename=path.name,
                    header_format=_nonempty_string(
                        entry["header_format"], "header_format"
                    ),
                    provider=data["provider"],
                    accuracy=data["accuracy"],
                    element=element,
                    pseudo_type=entry["pseudo_type"],
                    functional=data["functional"],
                    relativistic=entry_relativistic,
                    z_valence=entry["z_valence"],
                    table_id=data["id"],
                    asset_path=relative_path,
                    cutoffs=_published_cutoffs(entry, element, data["provider"]),
                    cutoff_hints=entry.get("cutoff_hints"),
                    source_identifier=entry["source_identifier"],
                    content_sha256=verified.sha256,
                    content_size_bytes=verified.size,
                    frozen_4f_core=entry["frozen_4f_core"],
                    pseudo_info={
                        "table_version": data["version"],
                        "table_relativistic": data["relativistic"],
                        "licence": data["licence"],
                        "citation": data["citation"],
                        "upf_relativistic": entry_relativistic,
                    },
                )
            )
            elements.append(element)
            paths.append(relative_path)

        if len(elements) != len(set(elements)) or len(paths) != len(set(paths)):
            raise ValueError(
                "pseudopotential entries must have unique elements and paths"
            )
        if table is not None and set(elements) != set(table.elements):
            raise ValueError(
                "pseudopotential manifest coverage disagrees with registry"
            )
        return tuple(metadata)
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise AssetCorrupt(
            f"invalid installed pseudopotential manifest for "
            f"{installed.id}@{installed.version}: {error}"
        ) from error


def _published_cutoffs(
    entry: dict[str, Any], element: str, provider: str
) -> PseudoCutoffs:
    """The entry's cutoffs as its provider publishes them. PseudoDojo
    publishes only wavefunction cutoff hints: the ``ecutrho_ry`` its
    manifests store is ``_extract_pseudodojo_pseudos``'s
    charge_density_dual x high, so it is validated with the rest of the
    manifest but read as ``None``, and the cutoffs advisor derives and
    labels the density cutoff (#180)."""
    ecutwfc_ry = finite_positive_cutoff(entry["ecutwfc_ry"], f"{element} ecutwfc_ry")
    ecutrho_ry = finite_positive_cutoff(entry["ecutrho_ry"], f"{element} ecutrho_ry")
    if provider == "pseudodojo":
        return {"ecutwfc_ry": ecutwfc_ry, "ecutrho_ry": None}
    return {"ecutwfc_ry": ecutwfc_ry, "ecutrho_ry": ecutrho_ry}


def _validate_entry_shape(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise ValueError("pseudopotential entries must be objects")
    fields = set(entry)
    missing = sorted(_ENTRY_FIELDS - fields)
    extra = sorted(fields - (_ENTRY_FIELDS | _OPTIONAL_ENTRY_FIELDS))
    if missing or extra:
        missing_names = ", ".join(missing) or "none"
        extra_names = ", ".join(extra) or "none"
        raise ValueError(
            f"pseudopotential entry fields mismatch; "
            f"missing: {missing_names}; extra: {extra_names}"
        )
    digest = entry["md5"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{32}", digest) is None:
        raise ValueError("pseudopotential entry md5 is invalid")
    if not isinstance(entry["frozen_4f_core"], bool):
        raise ValueError("frozen_4f_core must be a boolean")
    if entry["source_identifier"] is not None:
        _nonempty_string(entry["source_identifier"], "source_identifier")
    upf_relativistic = entry.get("upf_relativistic")
    if upf_relativistic is not None and upf_relativistic not in _RELATIVISTIC:
        raise ValueError(f"unsupported UPF relativistic treatment {upf_relativistic!r}")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- PseudoDojo provider (v1 pseudo/import_pseudodojo.py) -------------------

HARTREE_TO_RYDBERG = 2.0
_MD5 = re.compile(r"[0-9a-fA-F]{32}")
_PSEUDODOJO_LICENCE_NOTICE = """\
PseudoDojo pseudopotentials are distributed under the Creative Commons
Attribution 4.0 International licence (CC BY 4.0), as the PseudoDojo project
states in https://github.com/abinit/pseudo_dojo/blob/404896295771/README.md#license

Licence: https://creativecommons.org/licenses/by/4.0/
Source: https://www.pseudo-dojo.org/
Copy downloaded from: https://data-collections.psdi.ac.uk/records/8gc82-qm928
"""


def pseudodojo_preparer(table: PseudoTable):
    if table.provider != "pseudodojo":
        raise ValueError(f"not a PseudoDojo table: {table.id}")

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        try:
            reports = _pseudodojo_reports(sources["metadata"])
            entries = _extract_pseudodojo_pseudos(
                sources["pseudopotentials"], destination, table, reports
            )
            write_table_manifest(destination, table, entries)
            (destination / TABLE_LICENCE).write_text(
                _PSEUDODOJO_LICENCE_NOTICE, encoding="utf-8"
            )
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


def _pseudodojo_reports(archive: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for name, source in archive_files(archive, ".djrepo"):
        element = Path(name).stem
        report = json.load(source)
        if not isinstance(report, dict):
            raise PseudoImportError(f"dojo report for {element} must be a JSON object")
        digest = report.get("md5_upf")
        if not isinstance(digest, str) or _MD5.fullmatch(digest) is None:
            raise PseudoImportError(f"dojo report for {element} has invalid md5_upf")
        functional = _pseudodojo_report_functional(
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
                finite_positive_cutoff(values["ecut"], f"dojo {element} {level} ecut")
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


def _pseudodojo_report_functional(value: object, label: str) -> str:
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


def _extract_pseudodojo_pseudos(
    archive: Path,
    destination: Path,
    table: PseudoTable,
    reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if table.charge_density_dual is None:
        raise PseudoImportError(
            f"PseudoDojo table {table.id} has no charge-density dual"
        )
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    pseudos = destination / "pseudos"
    pseudos.mkdir()
    for name, source in archive_files(archive, ".upf"):
        element = Path(name).stem
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
        entry = extract_upf(
            source,
            pseudos / f"{element}.upf",
            element,
            table,
            report["md5"],
            f"{element}.upf does not match md5_upf",
        )
        cutoff_hints = report["cutoff_hints"]
        high = cutoff_hints["high"]
        # ecutrho_ry stays in what this preparation revision stores, so tables
        # installed before #180 and after it are the same bytes; the reader
        # does not hand it on as published (_published_cutoffs). Dropping it
        # needs a revision bump, which re-prepares every installed table.
        entry.update(
            ecutwfc_ry=high,
            ecutrho_ry=finite_positive_cutoff(
                high * table.charge_density_dual,
                f"dojo {element} charge-density cutoff",
            ),
            cutoff_hints=cutoff_hints,
            source_identifier=name,
            frozen_4f_core=table.frozen_4f_core,
        )
        entries.append(entry)
        seen.add(element)
    missing_reports = set(reports) - seen
    if missing_reports:
        raise PseudoImportError(
            "dojo reports describe absent UPFs: " + ", ".join(sorted(missing_reports))
        )
    return entries


# --- SSSP provider (v1 pseudo/import_sssp.py) -------------------------------


def sssp_preparer(table: PseudoTable):
    if table.provider != "sssp":
        raise ValueError(f"not an SSSP table: {table.id}")

    def prepare(sources: Mapping[str, Path], destination: Path) -> None:
        try:
            metadata = json.loads(sources["metadata"].read_text(encoding="utf-8"))
            if not isinstance(metadata, dict) or not metadata:
                raise PseudoImportError("SSSP metadata must be a non-empty object")
            entries = _extract_sssp_pseudos(
                sources["pseudopotentials"], destination, metadata, table
            )
            write_table_manifest(destination, table, entries)
            shutil.copyfile(sources["licence"], destination / TABLE_LICENCE)
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


def _sssp_metadata_by_filename(
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


def _extract_sssp_pseudos(
    archive: Path,
    destination: Path,
    metadata: dict[str, dict[str, Any]],
    table: PseudoTable,
) -> list[dict[str, Any]]:
    by_filename = _sssp_metadata_by_filename(metadata)
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


# --- provider dispatch (v1 pseudo/install.py) -------------------------------

_PREPARERS: Mapping[str, Callable[[PseudoTable], AssetPreparer]] = {
    "pseudodojo": pseudodojo_preparer,
    "sssp": sssp_preparer,
}


def installation_for(table: PseudoTable) -> AssetInstallation:
    try:
        prepare = _PREPARERS[table.provider]
    except KeyError as error:
        raise InvalidPseudoRegistry(
            f"table {table.id!r} has unsupported provider {table.provider!r}"
        ) from error
    return AssetInstallation(table.asset, prepare(table))


def table_installations(
    path: PathLike | None = None,
) -> tuple[AssetInstallation, ...]:
    return tuple(installation_for(table) for table in load_tables(path).values())
