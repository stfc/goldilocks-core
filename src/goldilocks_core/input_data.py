from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.assets.records import AssetSpec, InstalledAsset
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.files import FileReference, GeneratedFiles
from goldilocks_core.io.structures import (
    NormalizedStructure,
    StructureDocument,
    StructureSourceDocument,
)
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.model_registry import load_default_qrf_config
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.registry import load_tables
from goldilocks_core.selection import SelectionRecord, selection_portable
from goldilocks_core.serialization import (
    Portable,
    portable_record,
    to_jsonable,
    to_portable,
)
from goldilocks_core.types import JsonDict, PathLike


class InputArtifact(FileReference):
    content: Annotated[bytes, Portable()]


class RuntimeAssetIdentity(TypedDict):
    id: str
    version: str
    preparation_fingerprint: str


class RuntimeIdentity(TypedDict):
    core_version: str
    models: list[Annotated[JsonDict, Portable(ModelSpec)]]
    assets: list[RuntimeAssetIdentity]


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


class ManifestSource(StructureSourceDocument):
    path: str


class ManifestStructure(TypedDict):
    path: str
    metadata: StructureDocument


class ManifestRecords(TypedDict):
    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    k_points: KPointSelection
    selection: SelectionRecord
    generated_files: list[FileReference]


class InputManifest(TypedDict):
    source: ManifestSource
    canonical_structure: ManifestStructure
    intent: CalculationIntent
    hints: CalculationHints
    records: ManifestRecords
    pseudopotential_set: PseudopotentialSetIdentity
    runtime: RuntimeIdentity
    citations: list[str]


class DftInputData(TypedDict):
    schema_version: Literal[1]
    artifacts: tuple[InputArtifact, ...]
    pseudopotential_set: PseudopotentialSetIdentity
    runtime: RuntimeIdentity
    citations: tuple[str, ...]
    manifest: InputManifest


def input_data_portable(input_data: DftInputData) -> JsonDict:
    """Portable projection of DFT input data without artifact content."""
    return {
        "schema_version": input_data["schema_version"],
        "artifacts": [
            portable_record(artifact, InputArtifact)
            for artifact in input_data["artifacts"]
        ],
        "pseudopotential_set": to_jsonable(input_data["pseudopotential_set"]),
        "runtime": to_jsonable(input_data["runtime"]),
        "citations": list(input_data["citations"]),
        "manifest": to_jsonable(input_data["manifest"]),
    }


def assemble_dft_input_data(
    normalized_structure: NormalizedStructure,
    intent: CalculationIntent,
    hints: CalculationHints,
    analysis: StructureAnalysisRecord,
    advice: ParameterAdvice,
    k_points: KPointSelection,
    selection: SelectionRecord,
    generated_files: GeneratedFiles,
    pseudo_metadata: tuple[PseudoMetadata, ...],
    *,
    asset_store: AssetStore,
    pseudo_registry_path: PathLike | None,
    model_registry_path: PathLike | None,
    kmesh_model: ModelSpec | None,
    uses_default_kmesh_model: bool,
    metallicity_model: ModelSpec | None,
    uses_default_metallicity_model: bool,
) -> DftInputData:
    artifacts: list[InputArtifact] = []
    source = normalized_structure.source
    source_content = (
        source["content"].encode("utf-8")
        if source["content"] is not None
        else normalized_structure.canonical_cif.encode("utf-8")
    )
    source_name = (
        source["name"] if source["content"] is not None else "generated-structure.cif"
    )
    artifacts.append(
        {
            "path": f"source/{source_name}",
            "role": "structure_source",
            "content": source_content,
        }
    )
    artifacts.append(
        {
            "path": "structure/canonical.cif",
            "role": "canonical_structure",
            "content": normalized_structure.canonical_cif.encode("utf-8"),
        }
    )
    artifacts.extend(
        {
            "path": generated["path"],
            "role": generated["role"],
            "content": generated["content"].encode("utf-8"),
        }
        for generated in generated_files
    )

    selected_metadata = tuple(
        next(
            candidate
            for candidate in pseudo_metadata
            if candidate.element == selected["element"]
            and candidate.filename == selected["filename"]
            and candidate.filepath == selected["filepath"]
            and (
                candidate.table_id or candidate.provider or candidate.source_identifier
            )
            == selected["provenance"].data_source
        )
        for selected in selection["pseudopotentials"]
    )
    pseudo_artifacts, pseudo_set = _pseudopotential_material(
        selected_metadata,
        asset_store=asset_store,
        registry_path=pseudo_registry_path,
    )
    artifacts.extend(pseudo_artifacts)
    runtime_artifacts, runtime, runtime_citations = _runtime_material(
        analysis,
        k_points,
        asset_store=asset_store,
        registry_path=model_registry_path,
        custom_kmesh_model=kmesh_model,
        uses_default_kmesh_model=uses_default_kmesh_model,
        custom_metallicity_model=metallicity_model,
        uses_default_metallicity_model=uses_default_metallicity_model,
    )
    artifacts.extend(runtime_artifacts)
    citations = tuple(dict.fromkeys((pseudo_set["citation"], *runtime_citations)))
    manifest: InputManifest = {
        "source": {
            **source,
            "content": None,
            "path": artifacts[0]["path"],
        },
        "canonical_structure": {
            "path": "structure/canonical.cif",
            "metadata": normalized_structure.canonical_structure,
        },
        "intent": to_portable(intent),
        "hints": to_portable(hints),
        "records": {
            "analysis": to_portable(analysis),
            "advice": to_portable(advice),
            "k_points": to_portable(k_points),
            "selection": selection_portable(selection),
            "generated_files": [
                {"path": item["path"], "role": item["role"]} for item in generated_files
            ],
        },
        "pseudopotential_set": to_portable(pseudo_set),
        "runtime": to_portable(runtime),
        "citations": list(citations),
    }
    return {
        "schema_version": 1,
        "artifacts": tuple(artifacts),
        "pseudopotential_set": pseudo_set,
        "runtime": runtime,
        "citations": citations,
        "manifest": manifest,
    }


@dataclass(frozen=True, slots=True)
class _ModelMaterial:
    spec: ModelSpec
    asset: AssetSpec | None
    licence_path: str


def _runtime_material(
    analysis: StructureAnalysisRecord,
    k_points: KPointSelection,
    *,
    asset_store: AssetStore,
    registry_path: PathLike | None,
    custom_kmesh_model: ModelSpec | None,
    uses_default_kmesh_model: bool,
    custom_metallicity_model: ModelSpec | None,
    uses_default_metallicity_model: bool,
) -> tuple[list[InputArtifact], RuntimeIdentity, tuple[str, ...]]:
    materials = _used_model_material(
        analysis,
        k_points,
        registry_path=registry_path,
        custom_kmesh_model=custom_kmesh_model,
        uses_default_kmesh_model=uses_default_kmesh_model,
        custom_metallicity_model=custom_metallicity_model,
        uses_default_metallicity_model=uses_default_metallicity_model,
    )
    artifacts: list[InputArtifact] = []
    identities: list[RuntimeAssetIdentity] = []
    citations: list[str] = []
    for material in materials:
        model = material.spec
        if material.asset is None:
            missing = [
                field
                for field in ("licence", "licence_text", "citation")
                if not isinstance(getattr(model, field), str)
                or not getattr(model, field).strip()
            ]
            if missing:
                raise ValueError(
                    f"Model {model.name!r} used for publication must declare "
                    "non-empty licence, licence_text, and citation"
                )
            citations.append(model.citation)
            artifacts.append(
                {
                    "path": material.licence_path,
                    "role": "licence",
                    "content": model.licence_text.encode("utf-8"),
                }
            )
            continue

        citations.append(model.citation)
        installed = asset_store.resolve_spec(material.asset)
        licence = next(file for file in material.asset.files if file.role == "licence")
        suffix = Path(licence.path).suffix or ".txt"
        licence_name = material.asset.id.replace("/", "_")
        artifacts.append(
            {
                "path": f"licences/{licence_name}-{material.asset.version}{suffix}",
                "role": "licence",
                "content": _read_installed_content(installed, licence.path),
            }
        )
        identities.append(
            {
                "id": installed.id,
                "version": installed.version,
                "preparation_fingerprint": installed.preparation_fingerprint,
            }
        )
    return (
        artifacts,
        {
            "core_version": version("goldilocks-core"),
            "models": [to_portable(item.spec) for item in materials],
            "assets": identities,
        },
        tuple(citations),
    )


def _used_model_material(
    analysis: StructureAnalysisRecord,
    k_points: KPointSelection,
    *,
    registry_path: PathLike | None,
    custom_kmesh_model: ModelSpec | None,
    uses_default_kmesh_model: bool,
    custom_metallicity_model: ModelSpec | None,
    uses_default_metallicity_model: bool,
) -> tuple[_ModelMaterial, ...]:
    kpoints_uses_model = k_points["provenance"].source == "model"
    analysis_uses_model = analysis["electronic_character_source"] == "model"
    if not kpoints_uses_model and not analysis_uses_model:
        return ()

    default_kmesh_used = (
        kpoints_uses_model and custom_kmesh_model is None and uses_default_kmesh_model
    )
    needs_metallicity = analysis_uses_model or default_kmesh_used
    needs_registry = default_kmesh_used or (
        needs_metallicity and uses_default_metallicity_model
    )
    config = load_default_qrf_config(registry_path) if needs_registry else None
    materials: list[_ModelMaterial] = []
    if kpoints_uses_model:
        if custom_kmesh_model is not None:
            materials.append(
                _ModelMaterial(
                    custom_kmesh_model,
                    None,
                    "licences/custom-kmesh-model.txt",
                )
            )
        elif uses_default_kmesh_model:
            materials.append(
                _ModelMaterial(
                    config.model,
                    config.model_asset,
                    "licences/k-point-model.txt",
                )
            )
        else:
            raise ValueError(
                "Custom KMeshService produced a model result without identity; "
                "supply a CalculationDraft.kmesh_model with explicit licence and "
                "citation material"
            )

    if needs_metallicity:
        if uses_default_metallicity_model:
            materials.append(
                _ModelMaterial(
                    config.metallicity_model,
                    config.metallicity_asset,
                    "licences/metallicity-model.txt",
                )
            )
        elif custom_metallicity_model is not None:
            materials.append(
                _ModelMaterial(
                    custom_metallicity_model,
                    None,
                    "licences/custom-metallicity-model.txt",
                )
            )
        else:
            raise ValueError(
                "Configured metallicity checkpoint produced a model result without "
                "identity; supply Runtime(metallicity_model=ModelSpec(...)) with "
                "explicit licence and citation material"
            )
    return tuple(materials)


def _pseudopotential_material(
    metadata: tuple[PseudoMetadata, ...],
    *,
    asset_store: AssetStore,
    registry_path: PathLike | None,
) -> tuple[list[InputArtifact], PseudopotentialSetIdentity]:
    table_ids = {item.table_id for item in metadata}
    if len(table_ids) == 1 and None not in table_ids:
        table_id = next(iter(table_ids))
        tables = {
            table.asset.id: table for table in load_tables(registry_path).values()
        }
        table = tables[table_id]
        installed = asset_store.resolve_spec(table.asset)
        artifacts = [
            {
                "path": f"pseudo/{item.filename}",
                "role": "pseudopotential",
                "content": _read_installed_content(
                    installed,
                    Path(item.filepath).relative_to(installed.root).as_posix(),
                ),
            }
            for item in metadata
        ]
        artifacts.append(
            {
                "path": f"licences/{table.id}.txt",
                "role": "licence",
                "content": _read_installed_content(installed, "LICENSE.txt"),
            }
        )
        return artifacts, {
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
        }

    artifacts: list[InputArtifact] = []
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
    return artifacts, pseudo_set


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


def _read_installed_content(installed: InstalledAsset, relative_path: str) -> bytes:
    file = next(item for item in installed.files if item.path == relative_path)
    payload = installed.path(relative_path).read_bytes()
    if len(payload) != file.size or hashlib.sha256(payload).hexdigest() != file.sha256:
        raise ValueError(
            f"Installed content {installed.id}@{installed.version}/{relative_path} "
            "differs from its verified inventory"
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
