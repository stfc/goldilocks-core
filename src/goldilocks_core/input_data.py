from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.files import (
    FileReference,
    GeneratedFiles,
    InputArtifact,
)
from goldilocks_core.io.structures import (
    NormalizedStructure,
    StructureDocument,
    StructureSourceDocument,
)
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.pseudo.source import (
    PseudopotentialMaterial,
    PseudopotentialSetIdentity,
)
from goldilocks_core.runtime.models import RuntimeIdentity, RuntimeMaterial
from goldilocks_core.selection import SelectionRecord, selection_portable
from goldilocks_core.serialization import portable_record, to_jsonable, to_portable


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


@dataclass(frozen=True, slots=True)
class InputRecords:
    """Completed scientific records and generated text for one calculation."""

    analysis: StructureAnalysisRecord
    advice: ParameterAdvice
    k_points: KPointSelection
    selection: SelectionRecord
    generated_files: GeneratedFiles


def input_data_portable(input_data: DftInputData) -> dict[str, Any]:
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
    records: InputRecords,
    pseudopotentials: PseudopotentialMaterial,
    runtime: RuntimeMaterial,
) -> DftInputData:
    """Combine completed records and verified, self-contained publication material."""
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
        for generated in records.generated_files
    )
    artifacts.extend(pseudopotentials.artifacts)
    artifacts.extend(runtime.artifacts)
    citations = tuple(
        dict.fromkeys((pseudopotentials.identity["citation"], *runtime.citations))
    )
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
            "analysis": to_portable(records.analysis),
            "advice": to_portable(records.advice),
            "k_points": to_portable(records.k_points),
            "selection": selection_portable(records.selection),
            "generated_files": [
                {"path": item["path"], "role": item["role"]}
                for item in records.generated_files
            ],
        },
        "pseudopotential_set": to_portable(pseudopotentials.identity),
        "runtime": to_portable(runtime.identity),
        "citations": list(citations),
    }
    return {
        "schema_version": 1,
        "artifacts": tuple(artifacts),
        "pseudopotential_set": pseudopotentials.identity,
        "runtime": runtime.identity,
        "citations": citations,
        "manifest": manifest,
    }
