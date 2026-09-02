from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.assets.records import AssetSpec, InstalledAsset
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.files import GeneratedFiles
from goldilocks_core.io.structures import NormalizedStructure
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.model_registry import QrfKpointsConfig, load_default_qrf_config
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.registry import load_tables
from goldilocks_core.selection import PseudopotentialSelection, SelectionRecord
from goldilocks_core.serialization import to_jsonable, to_portable
from goldilocks_core.types import JsonDict, PathLike


@dataclass(frozen=True, slots=True)
class GeneratedContent:
    content: bytes
    identity: str


@dataclass(frozen=True, slots=True)
class InstalledArtifactReference:
    asset_id: str
    asset_version: str
    preparation_fingerprint: str
    path: str


type ArtifactSource = GeneratedContent | InstalledArtifactReference


@dataclass(frozen=True, slots=True)
class InputArtifact:
    path: str
    role: str
    sha256: str
    size_bytes: int
    source: ArtifactSource
    media_type: str | None = None
    provenance: Provenance | None = None


@dataclass(frozen=True, slots=True)
class PseudopotentialSetIdentity:
    id: str
    version: str | None
    provider: str
    functional: str
    accuracy: str
    relativistic: str
    licence: str
    citation: str
    policy: JsonDict


@dataclass(frozen=True, slots=True)
class RuntimeAssetIdentity:
    id: str
    version: str
    role: str
    preparation_fingerprint: str
    model: JsonDict
    files: tuple[JsonDict, ...]


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    core_version: str
    models: tuple[JsonDict, ...] = ()
    assets: tuple[RuntimeAssetIdentity, ...] = ()


@dataclass(frozen=True, slots=True)
class DftInputData:
    artifacts: tuple[InputArtifact, ...]
    pseudopotential_set: PseudopotentialSetIdentity
    runtime: RuntimeIdentity
    citations: tuple[str, ...]
    manifest: JsonDict
    schema_version: Literal[1] = 1


@to_portable.register(GeneratedContent)
def _generated_content_portable(content: GeneratedContent) -> JsonDict:
    return {"kind": "generated", "identity": content.identity}


@to_portable.register(InstalledArtifactReference)
def _installed_artifact_reference_portable(
    reference: InstalledArtifactReference,
) -> JsonDict:
    return {
        "kind": "installed",
        "asset_id": reference.asset_id,
        "asset_version": reference.asset_version,
        "preparation_fingerprint": reference.preparation_fingerprint,
        "path": reference.path,
    }


@to_portable.register(InputArtifact)
def _input_artifact_portable(artifact: InputArtifact) -> JsonDict:
    return {
        "path": artifact.path,
        "role": artifact.role,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "media_type": artifact.media_type,
        "provenance": to_jsonable(artifact.provenance),
        "source": to_portable(artifact.source),
    }


@to_portable.register(DftInputData)
def _dft_input_data_portable(input_data: DftInputData) -> JsonDict:
    return {
        "schema_version": input_data.schema_version,
        "artifacts": [to_portable(artifact) for artifact in input_data.artifacts],
        "pseudopotential_set": to_portable(input_data.pseudopotential_set),
        "runtime": to_portable(input_data.runtime),
        "citations": list(input_data.citations),
        "manifest": to_jsonable(input_data.manifest),
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
        _generated_artifact(
            f"source/{source_name}",
            "structure_source",
            source_content,
            identity=f"structure-source:{hashlib.sha256(source_content).hexdigest()}",
            media_type="chemical/x-cif" if source["format"] == "cif" else "text/plain",
            provenance=Provenance(
                source="user_hint" if source["content"] is not None else "default",
                reason=f"Preserved {source['origin']} Structure Source.",
            ),
        )
    )
    artifacts.append(
        _generated_artifact(
            "structure/canonical.cif",
            "canonical_structure",
            normalized_structure.canonical_cif.encode("utf-8"),
            identity="canonical-structure:cif",
            media_type="chemical/x-cif",
            provenance=Provenance(
                source="analysis",
                reason="Canonical CIF produced during Structure normalization.",
            ),
        )
    )
    for generated in generated_files:
        payload = _validated_generated_input(generated.path, generated.content)
        artifacts.append(
            _generated_artifact(
                generated.path,
                generated.role,
                payload,
                identity=f"generated-input:{generated.path}",
                media_type="text/plain; charset=utf-8",
                provenance=Provenance(
                    source="analysis",
                    reason="Rendered by the selected target-code generator.",
                ),
            )
        )

    selected_metadata = _bind_selected_pseudo_metadata(selection, pseudo_metadata)
    pseudo_artifacts, pseudo_set = _pseudopotential_material(
        selection,
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
    citations = tuple(dict.fromkeys((pseudo_set.citation, *runtime_citations)))
    manifest = {
        "source": {
            **source,
            "content": None,
            "path": artifacts[0].path,
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
            "selection": to_portable(selection),
            "generated_files": [
                {"path": item.path, "role": item.role} for item in generated_files
            ],
        },
        "selected_artifacts": [
            to_portable(artifact)
            for artifact in artifacts
            if artifact.role == "pseudopotential"
        ],
        "pseudopotential_set": to_portable(pseudo_set),
        "runtime": to_portable(runtime),
        "citations": list(citations),
    }
    return DftInputData(
        artifacts=tuple(artifacts),
        pseudopotential_set=pseudo_set,
        runtime=runtime,
        citations=citations,
        manifest=manifest,
    )


def _bind_selected_pseudo_metadata(
    selection: SelectionRecord,
    metadata: tuple[PseudoMetadata, ...],
) -> tuple[PseudoMetadata, ...]:
    bound: list[PseudoMetadata] = []
    for selected in selection.pseudopotentials:
        matches = tuple(
            candidate
            for candidate in metadata
            if candidate.element == selected.element
            and candidate.filename == selected.filename
            and candidate.filepath == selected.filepath
            and _pseudo_source_identity(candidate) == selected.provenance.data_source
        )
        if not matches:
            raise ValueError(
                "Selected pseudopotential has no exact metadata candidate for "
                f"{selected.element}"
            )
        if len(matches) != 1:
            raise ValueError(
                "Selected pseudopotential metadata is ambiguous for "
                f"{selected.element}: {len(matches)} exact candidates"
            )
        bound.append(matches[0])
    return tuple(bound)


def _pseudo_source_identity(metadata: PseudoMetadata) -> str | None:
    return metadata.table_id or metadata.provider or metadata.source_identifier


def _generated_artifact(
    path: str,
    role: str,
    payload: bytes,
    *,
    identity: str,
    media_type: str | None = None,
    provenance: Provenance | None = None,
) -> InputArtifact:
    return InputArtifact(
        path=path,
        role=role,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        source=GeneratedContent(payload, identity),
        media_type=media_type,
        provenance=provenance,
    )


def _validated_generated_input(path: str, content: str) -> bytes:
    payload = content.encode("utf-8")
    if not payload or not content.endswith("\n"):
        raise ValueError(
            f"Rendered input {path!r} must be non-empty UTF-8 text ending in newline"
        )
    if path == "inputs/qe.in":
        required = (
            "&CONTROL",
            "&SYSTEM",
            "&ELECTRONS",
            "ATOMIC_SPECIES",
            "ATOMIC_POSITIONS",
            "K_POINTS",
        )
        missing = [token for token in required if token not in content]
        if missing:
            raise ValueError(
                f"Rendered Quantum ESPRESSO input is missing: {', '.join(missing)}"
            )
    return payload


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
    if not materials:
        return [], RuntimeIdentity(core_version=version("goldilocks-core")), ()

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
                _generated_artifact(
                    material.licence_path,
                    "licence",
                    model.licence_text.encode("utf-8"),
                    identity=f"model-licence:{model.name}@{model.version}",
                    media_type="text/plain; charset=utf-8",
                )
            )
            continue

        if not isinstance(model.citation, str) or not model.citation.strip():
            raise ValueError(
                f"Model {model.name!r} used for publication must declare a "
                "non-empty citation"
            )
        citations.append(model.citation)
        installed = asset_store.resolve_spec(material.asset)
        licence = next(file for file in material.asset.files if file.role == "licence")
        suffix = Path(licence.path).suffix or ".txt"
        licence_name = material.asset.id.replace("/", "_")
        artifacts.append(
            _installed_artifact(
                installed,
                licence.path,
                f"licences/{licence_name}-{material.asset.version}{suffix}",
                "licence",
                "text/markdown; charset=utf-8",
            )
        )
        identities.append(_runtime_asset_identity(material, installed))
    return (
        artifacts,
        RuntimeIdentity(
            core_version=version("goldilocks-core"),
            models=tuple(_published_model_identity(item.spec) for item in materials),
            assets=tuple(identities),
        ),
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
    kpoints_uses_model = k_points.provenance.source == "model"
    analysis_uses_model = analysis.electronic_character_source == "model"
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
            assert config is not None
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
        metallicity = _metallicity_material(
            config,
            custom_model=custom_metallicity_model,
            uses_default_model=uses_default_metallicity_model,
        )
        if not any(
            _model_material_identity(item) == _model_material_identity(metallicity)
            for item in materials
        ):
            materials.append(metallicity)
    return tuple(materials)


def _metallicity_material(
    config: QrfKpointsConfig | None,
    *,
    custom_model: ModelSpec | None,
    uses_default_model: bool,
) -> _ModelMaterial:
    if uses_default_model:
        assert config is not None
        return _ModelMaterial(
            config.metallicity_model,
            config.metallicity_asset,
            "licences/metallicity-model.txt",
        )
    if custom_model is None:
        raise ValueError(
            "Configured metallicity checkpoint produced a model result without "
            "identity; supply Runtime(metallicity_model=ModelSpec(...)) with "
            "explicit licence and citation material"
        )
    return _ModelMaterial(
        custom_model,
        None,
        "licences/custom-metallicity-model.txt",
    )


def _model_material_identity(material: _ModelMaterial) -> tuple[object, ...]:
    model = material.spec
    asset = material.asset
    return (
        model.name,
        model.version,
        model.model_type,
        model.target,
        model.feature_set,
        model.source,
        model.location,
        model.revision,
        model.licence,
        model.licence_text,
        model.citation,
        asset.id if asset is not None else None,
        asset.version if asset is not None else None,
        asset.preparation_fingerprint if asset is not None else None,
    )


def _runtime_asset_identity(
    material: _ModelMaterial, installed: InstalledAsset
) -> RuntimeAssetIdentity:
    assert material.asset is not None
    roles = {file.path: file.role for file in material.asset.files}
    installed_paths = {file.path for file in installed.files}
    if installed_paths != set(roles):
        raise ValueError(
            f"Installed model asset inventory differs from registered roles for "
            f"{installed.id}@{installed.version}"
        )
    return RuntimeAssetIdentity(
        id=installed.id,
        version=installed.version,
        role="model",
        preparation_fingerprint=installed.preparation_fingerprint,
        model=_published_model_identity(material.spec),
        files=tuple(
            {
                "path": file.path,
                "role": roles[file.path],
                "sha256": file.sha256,
                "size_bytes": file.size,
            }
            for file in installed.files
        ),
    )


def _published_model_identity(model: ModelSpec) -> JsonDict:
    return {
        "name": model.name,
        "version": model.version,
        "model_type": model.model_type,
        "target": model.target,
        "feature_set": model.feature_set,
        "source": model.source,
        "revision": model.revision,
        "licence": model.licence,
        "citation": model.citation,
    }


def _pseudopotential_material(
    selection: SelectionRecord,
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
            _installed_pseudo_artifact(selected, installed)
            for selected in selection.pseudopotentials
        ]
        artifacts.append(
            _installed_artifact(
                installed,
                "LICENSE.txt",
                f"licences/{table.id}.txt",
                "licence",
                "text/plain; charset=utf-8",
            )
        )
        return artifacts, PseudopotentialSetIdentity(
            id=table.id,
            version=table.version,
            provider=table.provider,
            functional=table.functional,
            accuracy=table.accuracy,
            relativistic=table.relativistic,
            licence=table.licence,
            citation=table.citation,
            policy={
                "accuracy": table.accuracy,
                "provider": table.provider,
                "relativistic": table.relativistic,
            },
        )
    if None not in table_ids:
        raise ValueError("Selected pseudopotentials must come from one installed set")

    artifacts: list[InputArtifact] = []
    for selected, item in zip(selection.pseudopotentials, metadata, strict=True):
        if selected.filepath is None or selected.filename is None:
            raise ValueError(
                f"Cannot assemble unresolved pseudopotential for {selected.element}."
            )
        artifacts.append(
            _generated_artifact(
                f"pseudo/{selected.filename}",
                "pseudopotential",
                _read_explicit_pseudo(item),
                identity=item.source_identifier or selected.filename,
                media_type="application/x-upf",
                provenance=selected.provenance,
            )
        )
    pseudo_set, licence_text = _explicit_pseudopotential_set(metadata)
    artifacts.append(
        _generated_artifact(
            "licences/explicit-local-pseudopotentials.txt",
            "licence",
            licence_text.encode("utf-8"),
            identity="licence:explicit-local-pseudopotentials",
            media_type="text/plain; charset=utf-8",
        )
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


def _installed_pseudo_artifact(
    selected: PseudopotentialSelection, installed: InstalledAsset
) -> InputArtifact:
    filepath = selected.filepath
    filename = selected.filename
    if filepath is None or filename is None:
        raise ValueError(
            f"Cannot assemble unresolved pseudopotential for {selected.element}."
        )
    try:
        relative = Path(filepath).relative_to(installed.root).as_posix()
    except ValueError as error:
        raise ValueError(
            f"Selected pseudopotential is outside installed asset {installed.id}"
        ) from error
    return _installed_artifact(
        installed,
        relative,
        f"pseudo/{filename}",
        "pseudopotential",
        "application/x-upf",
        provenance=selected.provenance,
    )


def _installed_artifact(
    installed: InstalledAsset,
    relative_path: str,
    output_path: str,
    role: str,
    media_type: str,
    *,
    provenance: Provenance | None = None,
) -> InputArtifact:
    installed.path(relative_path)
    file = next(item for item in installed.files if item.path == relative_path)
    return InputArtifact(
        path=output_path,
        role=role,
        sha256=file.sha256,
        size_bytes=file.size,
        source=InstalledArtifactReference(
            installed.id,
            installed.version,
            installed.preparation_fingerprint,
            relative_path,
        ),
        media_type=media_type,
        provenance=provenance,
    )


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
        PseudopotentialSetIdentity(
            id="explicit-local",
            version=None,
            provider=",".join(providers),
            functional=",".join(functionals),
            accuracy=",".join(accuracies),
            relativistic=",".join(relativistic),
            licence=licences,
            citation=citation,
            policy={"source": "operator_supplied", "selection": "per_element"},
        ),
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
