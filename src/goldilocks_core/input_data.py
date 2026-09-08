from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from importlib.metadata import version
from pathlib import Path

from goldilocks_core.assets import AssetSpec, AssetStore, InstalledAsset
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    DftInputData,
    GeneratedFiles,
    InputArtifact,
    KPointSelection,
    ModelSpec,
    ParameterAdvice,
    PathLike,
    PseudoMetadata,
    PseudopotentialSetIdentity,
    RuntimeAssetIdentity,
    RuntimeIdentity,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.contracts.types import JsonDict
from goldilocks_core.io.structures import NormalizedStructure
from goldilocks_core.ml.model_registry import QrfKpointsConfig
from goldilocks_core.pseudo.registry import load_tables


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
    kmesh_config: QrfKpointsConfig | None,
    metallicity_config: QrfKpointsConfig | None,
    kmesh_model: ModelSpec | None,
    uses_default_kmesh_model: bool,
    metallicity_model: ModelSpec | None,
    uses_default_metallicity_model: bool,
) -> DftInputData:
    artifacts: list[InputArtifact] = []
    source = normalized_structure.source
    source_content = (
        source.content.encode("utf-8")
        if source.content is not None
        else normalized_structure.canonical_cif.encode("utf-8")
    )
    source_name = (
        source.name if source.content is not None else "generated-structure.cif"
    )
    artifacts.append(
        InputArtifact(
            f"source/{source_name}",
            "structure_source",
            source_content,
        )
    )
    artifacts.append(
        InputArtifact(
            "structure/canonical.cif",
            "canonical_structure",
            normalized_structure.canonical_cif.encode("utf-8"),
        )
    )
    for generated in generated_files:
        artifacts.append(
            InputArtifact(
                generated.path,
                generated.role,
                generated.content.encode("utf-8"),
            )
        )

    selected_metadata = tuple(
        next(
            candidate
            for candidate in pseudo_metadata
            if candidate.element == selected.element
            and candidate.filename == selected.filename
            and candidate.filepath == selected.filepath
            and (
                candidate.table_id or candidate.provider or candidate.source_identifier
            )
            == selected.provenance.data_source
        )
        for selected in selection.pseudopotentials
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
        kmesh_config=kmesh_config,
        metallicity_config=metallicity_config,
        custom_kmesh_model=kmesh_model,
        uses_default_kmesh_model=uses_default_kmesh_model,
        custom_metallicity_model=metallicity_model,
        uses_default_metallicity_model=uses_default_metallicity_model,
    )
    artifacts.extend(runtime_artifacts)
    citations = tuple(dict.fromkeys((pseudo_set.citation, *runtime_citations)))
    manifest = {
        "source": {
            **source.to_dict(),
            "content": None,
            "path": artifacts[0].path,
        },
        "canonical_structure": {
            "path": "structure/canonical.cif",
            "metadata": normalized_structure.canonical_structure.to_dict(),
        },
        "intent": intent.to_dict(),
        "hints": hints.to_dict(),
        "records": {
            "analysis": analysis.to_dict(),
            "advice": advice.to_dict(),
            "k_points": k_points.to_dict(),
            "selection": selection.to_dict(),
            "generated_files": [
                {"path": item.path, "role": item.role} for item in generated_files
            ],
        },
        "pseudopotential_set": pseudo_set.to_dict(),
        "runtime": runtime.to_dict(),
        "citations": list(citations),
    }
    return DftInputData(
        artifacts=tuple(artifacts),
        pseudopotential_set=pseudo_set,
        runtime=runtime,
        citations=citations,
        manifest=manifest,
    )


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
    kmesh_config: QrfKpointsConfig | None,
    metallicity_config: QrfKpointsConfig | None,
    custom_kmesh_model: ModelSpec | None,
    uses_default_kmesh_model: bool,
    custom_metallicity_model: ModelSpec | None,
    uses_default_metallicity_model: bool,
) -> tuple[list[InputArtifact], RuntimeIdentity, tuple[str, ...]]:
    materials = _used_model_material(
        analysis,
        k_points,
        kmesh_config=kmesh_config,
        metallicity_config=metallicity_config,
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
                InputArtifact(
                    material.licence_path,
                    "licence",
                    model.licence_text.encode("utf-8"),
                )
            )
            continue

        citations.append(model.citation)
        installed = asset_store.resolve_spec(material.asset)
        identity = RuntimeAssetIdentity(
            id=installed.id,
            version=installed.version,
            preparation_fingerprint=installed.preparation_fingerprint,
        )
        if identity in identities:
            continue
        licence = next(file for file in material.asset.files if file.role == "licence")
        suffix = Path(licence.path).suffix or ".txt"
        licence_name = material.asset.id.replace("/", "_")
        artifacts.append(
            InputArtifact(
                f"licences/{licence_name}-{material.asset.version}{suffix}",
                "licence",
                _read_installed_content(installed, licence.path),
            )
        )
        identities.append(identity)
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
    kmesh_config: QrfKpointsConfig | None,
    metallicity_config: QrfKpointsConfig | None,
    custom_kmesh_model: ModelSpec | None,
    uses_default_kmesh_model: bool,
    custom_metallicity_model: ModelSpec | None,
    uses_default_metallicity_model: bool,
) -> tuple[_ModelMaterial, ...]:
    materials: list[_ModelMaterial] = []
    if k_points.provenance.source == "model":
        if custom_kmesh_model is not None:
            materials.append(
                _ModelMaterial(
                    custom_kmesh_model, None, "licences/custom-kmesh-model.txt"
                )
            )
        elif uses_default_kmesh_model and kmesh_config is not None:
            materials.append(
                _ModelMaterial(
                    kmesh_config.model,
                    kmesh_config.model_asset,
                    "licences/k-point-model.txt",
                )
            )
            # QRF uses its own classifier resources for feature extraction.
            materials.append(
                _metallicity_material(
                    kmesh_config,
                    custom_metallicity_model,
                    uses_default_metallicity_model,
                )
            )
        else:
            raise ValueError(
                "KMeshService produced a model result without loaded identity; "
                "supply a CalculationDraft.kmesh_model with explicit licence and "
                "citation material"
            )

    if analysis.electronic_character_source == "model":
        material = _metallicity_material(
            metallicity_config,
            custom_metallicity_model,
            uses_default_metallicity_model,
        )
        if material not in materials:
            if material.asset is None and any(
                item.licence_path == material.licence_path for item in materials
            ):
                material = replace(
                    material, licence_path="licences/analysis-metallicity-model.txt"
                )
            materials.append(material)
    return tuple(materials)


def _metallicity_material(
    config: QrfKpointsConfig | None,
    custom_model: ModelSpec | None,
    uses_default: bool,
) -> _ModelMaterial:
    if uses_default and config is not None:
        return _ModelMaterial(
            config.metallicity_model,
            config.metallicity_asset,
            "licences/metallicity-model.txt",
        )
    if not uses_default and custom_model is not None:
        return _ModelMaterial(
            custom_model, None, "licences/custom-metallicity-model.txt"
        )
    raise ValueError(
        "Metallicity classifier produced a model result without loaded identity; "
        "supply Runtime(metallicity_model=ModelSpec(...)) with explicit licence "
        "and citation material"
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
            InputArtifact(
                f"pseudo/{item.filename}",
                "pseudopotential",
                _read_installed_content(
                    installed,
                    Path(item.filepath).relative_to(installed.root).as_posix(),
                ),
            )
            for item in metadata
        ]
        artifacts.append(
            InputArtifact(
                f"licences/{table.id}.txt",
                "licence",
                _read_installed_content(installed, "LICENSE.txt"),
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
                "preparation_fingerprint": installed.preparation_fingerprint,
            },
        )

    artifacts: list[InputArtifact] = []
    for item in metadata:
        artifacts.append(
            InputArtifact(
                f"pseudo/{item.filename}",
                "pseudopotential",
                _read_explicit_pseudo(item),
            )
        )
    pseudo_set, licence_text = _explicit_pseudopotential_set(metadata)
    artifacts.append(
        InputArtifact(
            "licences/explicit-local-pseudopotentials.txt",
            "licence",
            licence_text.encode("utf-8"),
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
        PseudopotentialSetIdentity(
            id="explicit-local",
            version=None,
            provider=",".join(providers),
            functional=",".join(functionals),
            accuracy=",".join(accuracies),
            relativistic=",".join(relativistic),
            licence=licences,
            citation=citation,
            policy={
                "source": "operator_supplied",
                "selection": "per_element",
                "sources": {item.filename: item.source_identifier for item in metadata},
            },
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
