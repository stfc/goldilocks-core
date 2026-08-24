from __future__ import annotations

import hashlib
from importlib.metadata import version
from pathlib import Path

from goldilocks_core.assets import AssetStore, InstalledAsset
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    DftInputData,
    GeneratedContent,
    GeneratedFiles,
    InputArtifact,
    InstalledArtifactReference,
    KPointSelection,
    ParameterAdvice,
    PathLike,
    Provenance,
    PseudoMetadata,
    PseudopotentialSelection,
    PseudopotentialSetIdentity,
    RuntimeAssetIdentity,
    RuntimeIdentity,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.contracts.types import JsonDict
from goldilocks_core.io.structures import NormalizedStructure
from goldilocks_core.ml.model_registry import model_asset_specs
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
    model_registry_path: PathLike | None,
    runtime_models: tuple[JsonDict, ...],
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
        _generated_artifact(
            f"source/{source_name}",
            "structure_source",
            source_content,
            identity=f"structure-source:{hashlib.sha256(source_content).hexdigest()}",
            media_type="chemical/x-cif" if source.format == "cif" else "text/plain",
            provenance=Provenance(
                source="user_hint" if source.content is not None else "default",
                reason=f"Preserved {source.origin} Structure Source.",
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

    metadata_by_element = {item.element: item for item in pseudo_metadata}
    selected_metadata = tuple(
        metadata_by_element[item.element] for item in selection.pseudopotentials
    )
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
        models=runtime_models,
    )
    artifacts.extend(runtime_artifacts)
    citations = (pseudo_set.citation, *runtime_citations)
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
        "selected_artifacts": [
            artifact.to_dict()
            for artifact in artifacts
            if artifact.role == "pseudopotential"
        ],
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


def _runtime_material(
    analysis: StructureAnalysisRecord,
    k_points: KPointSelection,
    *,
    asset_store: AssetStore,
    registry_path: PathLike | None,
    models: tuple[JsonDict, ...],
) -> tuple[list[InputArtifact], RuntimeIdentity, tuple[str, ...]]:
    uses_model = (
        k_points.provenance.source == "model"
        or analysis.electronic_character_source == "model"
    )
    if not uses_model:
        return [], RuntimeIdentity(core_version=version("goldilocks-core")), ()

    artifacts: list[InputArtifact] = []
    identities: list[RuntimeAssetIdentity] = []
    citations: list[str] = []
    for spec in sorted(model_asset_specs(registry_path), key=lambda item: item.id):
        installed = asset_store.resolve_spec(spec)
        licence = next(file for file in spec.files if file.role == "licence")
        suffix = Path(licence.path).suffix or ".txt"
        artifacts.append(
            _installed_artifact(
                installed,
                licence.path,
                f"licences/{spec.id}-{spec.version}{suffix}",
                "licence",
                "text/markdown; charset=utf-8",
            )
        )
        identities.append(RuntimeAssetIdentity(spec.id, spec.version, "model"))
        citations.append(licence.url)
    return (
        artifacts,
        RuntimeIdentity(
            core_version=version("goldilocks-core"),
            models=models,
            assets=tuple(identities),
        ),
        tuple(citations),
    )


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
        table = load_tables(registry_path)[table_id]
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
    metadata_by_element = {item.element: item for item in metadata}
    for selected in selection.pseudopotentials:
        if selected.filepath is None or selected.filename is None:
            raise ValueError(
                f"Cannot assemble unresolved pseudopotential for {selected.element}."
            )
        item = metadata_by_element[selected.element]
        artifacts.append(
            _generated_artifact(
                f"pseudo/{selected.filename}",
                "pseudopotential",
                Path(selected.filepath).read_bytes(),
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
            installed.id, installed.version, relative_path
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
