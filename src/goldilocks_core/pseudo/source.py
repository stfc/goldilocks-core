from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from pymatgen.core import Element, Structure

from goldilocks_core.advice.parameters import PseudopotentialRequirements
from goldilocks_core.assets.records import InstalledAsset
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.generation.files import InputArtifact
from goldilocks_core.pseudo.installed import load_installed_table
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.pseudo.registry import PseudoTable, load_tables
from goldilocks_core.selection import SelectionRecord, select_pseudopotentials
from goldilocks_core.types import JsonDict, PathLike


class RegisteredPseudoPolicy(TypedDict):
    accuracy: str
    provider: str
    relativistic: str
    preparation_fingerprint: str


class ExplicitPseudoPolicy(TypedDict):
    source: Literal["operator_supplied"]
    selection: Literal["per_element"]
    sources: dict[str, str | None]


class PseudopotentialSetIdentity(TypedDict):
    id: str
    version: str | None
    provider: str
    functional: str
    accuracy: str
    relativistic: str
    licence: str
    citation: str
    policy: RegisteredPseudoPolicy | ExplicitPseudoPolicy


@dataclass(frozen=True, slots=True)
class PseudopotentialMaterial:
    artifacts: tuple[InputArtifact, ...]
    identity: PseudopotentialSetIdentity


class PseudoTableMismatch(ExpectedFailure, ValueError):
    kind = "pseudo_table_mismatch"


class PseudoResolution:
    """Resolve, select, and snapshot one request's pseudopotentials lazily.

    Selection needs metadata only. Publication binds the selected files and legal
    material to verified bytes without exposing source state to the task graph.
    """

    def __init__(
        self,
        *,
        metadata: tuple[PseudoMetadata, ...] | None = None,
        root: PathLike | None = None,
        table_id: str | None = None,
        store: AssetStore,
        registry_path: PathLike | None = None,
    ) -> None:
        self._root = root
        self._table_id = table_id
        self._store = store
        self._registry_path = registry_path
        self._metadata = metadata
        self._selection: SelectionRecord | None = None
        self._table: PseudoTable | None = None
        self._installed: InstalledAsset | None = None
        self._material: PseudopotentialMaterial | None = None

    def select(
        self, structure: Structure, requirements: PseudopotentialRequirements
    ) -> SelectionRecord:
        if self._metadata is None:
            if self._root is not None:
                self._metadata = tuple(load_pseudo_metadata(self._root))
            else:
                self._table = select_compatible_table(
                    load_tables(self._registry_path),
                    table_id=self._table_id,
                    elements={
                        element.symbol for element in structure.composition.elements
                    },
                    requirements=requirements,
                )
                self._installed = self._store.resolve_spec(self._table.asset)
                self._metadata = load_installed_table(
                    self._installed, table=self._table
                )
        self._selection = select_pseudopotentials(
            structure, requirements, self._metadata
        )
        self._material = None
        return self._selection

    def materialize(self) -> PseudopotentialMaterial:
        if self._material is not None:
            return self._material
        if self._selection is None or self._metadata is None:
            raise RuntimeError("Pseudopotentials must be selected before publication")
        selected_metadata = tuple(
            next(
                candidate
                for candidate in self._metadata
                if candidate.element == selected["element"]
                and candidate.filename == selected["filename"]
                and candidate.filepath == selected["filepath"]
                and (
                    candidate.table_id
                    or candidate.provider
                    or candidate.source_identifier
                )
                == selected["provenance"].data_source
            )
            for selected in self._selection["pseudopotentials"]
        )
        table_ids = {item.table_id for item in selected_metadata}
        if self._table is None and len(table_ids) == 1 and None not in table_ids:
            table_id = next(iter(table_ids))
            self._table = next(
                table
                for table in load_tables(self._registry_path).values()
                if table.asset.id == table_id
            )
            self._installed = self._store.resolve_spec(self._table.asset)
        self._material = _pseudopotential_material(
            selected_metadata, self._table, self._installed
        )
        return self._material


def select_compatible_table(
    tables: dict[str, PseudoTable],
    *,
    table_id: str | None,
    elements: set[str],
    requirements: JsonDict,
) -> PseudoTable:
    """Select an explicit or preferred compatible pseudopotential table."""
    if table_id is None:
        return _automatic_table(tables, elements, requirements)
    try:
        table = tables[table_id]
    except KeyError as error:
        choices = ", ".join(sorted(tables))
        raise PseudoTableMismatch(
            f"unknown pseudopotential table {table_id!r}; available: {choices}"
        ) from error

    problems = _table_problems(table, elements, requirements)
    if not problems:
        return table
    matches = [
        candidate.id
        for candidate in tables.values()
        if not _table_problems(candidate, elements, requirements)
    ]
    alternatives = ", ".join(sorted(matches)) or "none"
    raise PseudoTableMismatch(
        f"pseudopotential table {table.id!r} does not satisfy the request: "
        f"{'; '.join(problems)}; matching tables: {alternatives}"
    )


def is_table_eligible_for_elements(table: PseudoTable, elements: set[str]) -> bool:
    """Return whether a table may serve every element under Core policy."""
    return all(element in table.elements for element in elements) and (
        not _requires_sssp(elements) or table.provider == "sssp"
    )


def _automatic_table(
    tables: dict[str, PseudoTable],
    elements: set[str],
    requirements: JsonDict,
) -> PseudoTable:
    matches = [
        table
        for table in tables.values()
        if not _table_problems(table, elements, requirements)
    ]
    if not matches:
        requested = (
            f"{requirements['functional']} {requirements['accuracy']} "
            f"{requirements['relativistic']}"
        )
        raise PseudoTableMismatch(
            f"no pseudopotential table satisfies {requested} for "
            + ", ".join(sorted(elements))
        )
    provider = "sssp" if _requires_sssp(elements) else "pseudodojo"
    return min(
        matches,
        key=lambda table: (table.provider != provider, table.id),
    )


def _requires_sssp(elements: set[str]) -> bool:
    return any(
        element.is_lanthanoid or element.is_actinoid
        for element in map(Element, elements)
    )


def _table_problems(
    table: PseudoTable,
    elements: set[str],
    requirements: JsonDict,
) -> list[str]:
    problems: list[str] = []
    if table.functional != requirements["functional"]:
        problems.append(
            f"functional is {table.functional}, requested {requirements['functional']}"
        )
    if table.accuracy != requirements["accuracy"]:
        problems.append(
            f"accuracy is {table.accuracy}, requested {requirements['accuracy']}"
        )
    if table.relativistic != requirements["relativistic"]:
        problems.append(
            f"relativistic treatment is {table.relativistic}, "
            f"requested {requirements['relativistic']}"
        )
    if _requires_sssp(elements) and table.provider != "sssp":
        problems.append("lanthanide and actinide elements require an SSSP table")
    missing = sorted(elements - set(table.elements))
    if missing:
        problems.append("missing elements " + ", ".join(missing))
    return problems


def _pseudopotential_material(
    metadata: tuple[PseudoMetadata, ...],
    table: PseudoTable | None,
    installed: InstalledAsset | None,
) -> PseudopotentialMaterial:
    if table is not None and installed is not None:
        artifacts: list[InputArtifact] = [
            {
                "path": f"pseudo/{item.filename}",
                "role": "pseudopotential",
                "content": installed.read_bytes(
                    Path(item.filepath).relative_to(installed.root).as_posix()
                ),
            }
            for item in metadata
        ]
        artifacts.append(
            {
                "path": f"licences/{table.id}.txt",
                "role": "licence",
                "content": installed.read_bytes("LICENSE.txt"),
            }
        )
        return PseudopotentialMaterial(
            tuple(artifacts),
            {
                "id": table.id,
                "version": table.version,
                "provider": table.provider,
                "functional": table.functional,
                "accuracy": table.accuracy,
                "relativistic": table.relativistic,
                "licence": table.licence,
                "citation": table.citation,
                "policy": {
                    "accuracy": table.accuracy,
                    "provider": table.provider,
                    "relativistic": table.relativistic,
                    "preparation_fingerprint": installed.preparation_fingerprint,
                },
            },
        )

    artifacts = []
    for item in metadata:
        artifacts.append(
            {
                "path": f"pseudo/{item.filename}",
                "role": "pseudopotential",
                "content": _read_explicit_pseudo(item),
            }
        )
    pseudo_set, licence_text = _explicit_pseudopotential_set(metadata)
    artifacts.append(
        {
            "path": "licences/explicit-local-pseudopotentials.txt",
            "role": "licence",
            "content": licence_text.encode("utf-8"),
        }
    )
    return PseudopotentialMaterial(tuple(artifacts), pseudo_set)


def _read_explicit_pseudo(metadata: PseudoMetadata) -> bytes:
    if metadata.content_sha256 is None or metadata.content_size_bytes is None:
        raise ValueError(
            f"Explicit pseudopotential {metadata.filename!r} lacks a parsed "
            "content binding"
        )
    payload = Path(metadata.filepath).read_bytes()
    if (
        len(payload) != metadata.content_size_bytes
        or hashlib.sha256(payload).hexdigest() != metadata.content_sha256
    ):
        raise ValueError(
            f"Explicit pseudopotential {metadata.filename!r} differs from its "
            "parsed content binding"
        )
    return payload


def _explicit_pseudopotential_set(
    metadata: tuple[PseudoMetadata, ...],
) -> tuple[PseudopotentialSetIdentity, str]:
    details = tuple(item.pseudo_info for item in metadata)
    licences = _one_value(details, "licence")
    licence_text = _one_value(details, "licence_text")
    citation = _one_value(details, "citation")
    providers = sorted({item.provider or "unknown" for item in metadata})
    functionals = sorted({item.functional or "unknown" for item in metadata})
    accuracies = sorted({item.accuracy or "unknown" for item in metadata})
    relativistic = sorted({item.relativistic or "unknown" for item in metadata})
    return (
        {
            "id": "explicit-local",
            "version": None,
            "provider": ",".join(providers),
            "functional": ",".join(functionals),
            "accuracy": ",".join(accuracies),
            "relativistic": ",".join(relativistic),
            "licence": licences,
            "citation": citation,
            "policy": {
                "source": "operator_supplied",
                "selection": "per_element",
                "sources": {item.filename: item.source_identifier for item in metadata},
            },
        },
        licence_text,
    )


def _one_value(documents: tuple[JsonDict, ...], field: str) -> str:
    values = {document.get(field) for document in documents}
    if len(values) != 1:
        raise ValueError(
            f"Explicit pseudopotential metadata must declare one {field!r} value"
        )
    value = values.pop()
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"Explicit pseudopotential metadata must declare non-empty {field!r} text"
        )
    return value
