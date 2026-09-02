from __future__ import annotations

import types
from dataclasses import MISSING, fields, is_dataclass
from functools import reduce
from operator import or_
from typing import Any, Literal, TypeAliasType, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, JsonValue, create_model, model_validator

from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.input_data import DftInputData
from goldilocks_core.io.structures import Matrix3, Vector3
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.runtime.registry import record_types_by_id
from goldilocks_core.selection import PseudopotentialSelection
from goldilocks_core.types import (
    CalcTask,
    CodeName,
    Dimensionality,
    ElectronicCharacter,
    JsonDict,
    KPointGrid,
    PseudoAccuracy,
    PseudoType,
    RelativisticTreatment,
    SmearingType,
    VdwMethod,
)

_STRICT = ConfigDict(extra="forbid", strict=True)


def _model_from_dataclass(contract: type, name: str) -> type[BaseModel]:
    hints = get_type_hints(contract)
    definitions: dict[str, Any] = {}
    for item in fields(contract):
        annotation = hints[item.name]
        if item.default is not MISSING:
            definitions[item.name] = (annotation, item.default)
        elif item.default_factory is not MISSING:
            definitions[item.name] = (annotation, item.default_factory)
        else:
            definitions[item.name] = (annotation, ...)
    return create_model(name, __config__=_STRICT, **definitions)


_IntentBase = _model_from_dataclass(CalculationIntent, "CalculationIntentBase")
IntentDocument = create_model(
    "CalculationIntent",
    __base__=_IntentBase,
)
_HintsBase = _model_from_dataclass(CalculationHints, "CalculationHintsBase")
HintsDocument = create_model(
    "CalculationHints",
    __base__=_HintsBase,
    k_grid=(list[int] | None, None),
)


def _inline_structure(value: Any) -> Any:
    if isinstance(value, str) or (
        isinstance(value, dict) and (value.get("kind") == "path" or "path" in value)
    ):
        raise ValueError(
            "Transports do not accept file paths. Read the file and pass its "
            "text as an inline Structure Source."
        )
    return value


InlineStructureDocument = create_model(
    "InlineStructureSource",
    __config__=_STRICT,
    __validators__={
        "inline_structure": model_validator(mode="before")(_inline_structure)
    },
    kind=(Literal["inline"], "inline"),
    name=(str, ...),
    content=(str, ...),
    format=(Literal["cif", "poscar"] | None, None),
)
InspectRequestDocument = create_model(
    "StructureInspectionRequest",
    __config__=_STRICT,
    source=(InlineStructureDocument, ...),
)
_SpeciesOccupancyDocument = create_model(
    "SpeciesOccupancy",
    symbol=(str, ...),
    label=(str, ...),
    occupancy=(float, ...),
    oxidation_state=(float | None, None),
)
_StructureSiteDocument = create_model(
    "StructureSiteDocument",
    fractional_coordinates=(Vector3, ...),
    cartesian_coordinates_angstrom=(Vector3, ...),
    species=(tuple[_SpeciesOccupancyDocument, ...], ...),
)
_LatticeDocument = create_model(
    "LatticeDocument",
    vectors_angstrom=(Matrix3, ...),
    lengths_angstrom=(Vector3, ...),
    angles_degrees=(Vector3, ...),
    volume_angstrom3=(float, ...),
)
_StructureDocument = create_model(
    "StructureDocument",
    schema_version=(int, ...),
    formula=(str, ...),
    reduced_formula=(str, ...),
    site_count=(int, ...),
    lattice=(_LatticeDocument, ...),
    periodicity=(tuple[bool, bool, bool], ...),
    sites=(tuple[_StructureSiteDocument, ...], ...),
)
StructureSourceDocument = create_model(
    "StructureSourceDocument",
    origin=(Literal["inline", "path", "generated"], ...),
    name=(str, ...),
    format=(str, ...),
    content=(str | None, ...),
    sha256=(str | None, ...),
    size_bytes=(int | None, ...),
)
StructureInspectionDocument = create_model(
    "StructureInspection",
    source=(StructureSourceDocument, ...),
    structure=(_StructureDocument, ...),
    canonical_cif=(str, ...),
    schema_version=(int, 1),
)
DraftDocument = create_model(
    "CalculationDraft",
    __config__=_STRICT,
    structure=(InlineStructureDocument, ...),
    intent=(IntentDocument | None, None),
    hints=(HintsDocument | None, None),
    pseudo_table=(str | None, None),
)
PresetSelectionDocument = create_model(
    "PresetSelection", __config__=_STRICT, preset=(str, ...)
)
RecordSelectionDocument = create_model(
    "RecordSelection", __config__=_STRICT, records=(list[str], ...)
)
type SelectionDocument = PresetSelectionDocument | RecordSelectionDocument
MemoryOutputDocument = create_model(
    "MemoryOutput", __config__=_STRICT, kind=(Literal["memory"], ...)
)
ComputeRequestDocument = create_model(
    "ComputeRequest",
    __config__=_STRICT,
    draft=(DraftDocument, ...),
    selection=(SelectionDocument, ...),
)

_CapabilityStageDocument = create_model(
    "StageCapability",
    id=(str, ...),
    name=(str, ...),
    description=(str, ...),
    input_record_ids=(tuple[str, ...], ...),
    output_record_id=(str, ...),
)
_CapabilityPresetDocument = create_model(
    "PresetCapability",
    id=(str, ...),
    name=(str, ...),
    output_record_ids=(tuple[str, ...], ...),
)
_CapabilityTaskDocument = create_model(
    "CalculationTaskCapability",
    id=(str, ...),
    revision=(str, ...),
    name=(str, ...),
    description=(str, ...),
    stages=(tuple[_CapabilityStageDocument, ...], ...),
    presets=(tuple[_CapabilityPresetDocument, ...], ...),
    selectable_record_ids=(tuple[str, ...], ...),
)
_CapabilityModelDocument = create_model(
    "ModelCapability",
    id=(str, ...),
    name=(str, ...),
    version=(str, ...),
    role=(str, ...),
    model_type=(str, ...),
    target=(str, ...),
    feature_set=(str, ...),
    source=(str, ...),
    revision=(str | None, ...),
)
_CapabilityPseudopotentialSetDocument = create_model(
    "PseudopotentialSetCapability",
    id=(str, ...),
    version=(str, ...),
    provider=(str, ...),
    upstream_name=(str, ...),
    functional=(str, ...),
    accuracy=(str, ...),
    relativistic_treatment=(str, ...),
    supported_elements=(tuple[str, ...], ...),
    licence=(str, ...),
    citation=(str, ...),
    default=(bool, ...),
)
_CapabilityIntentDocument = create_model(
    "CalculationIntent",
    code=(CodeName, "quantum_espresso"),
    task=(CalcTask, "scf_single_point"),
    functional=(str, "PBEsol"),
    pseudo_accuracy=(PseudoAccuracy, "efficiency"),
)
_CapabilityHintsDocument = create_model(
    "CalculationHints",
    __doc__=CalculationHints.__doc__,
    k_spacing=(float | None, None),
    k_grid=(KPointGrid | None, None),
    smearing_type=(SmearingType | None, None),
    smearing_width_ry=(float | None, None),
    spin_polarized=(bool | None, None),
    spin_orbit_coupling=(bool | None, None),
    pseudo_accuracy=(PseudoAccuracy | None, None),
    pseudo_type=(PseudoType | None, None),
    relativistic_mode=(RelativisticTreatment | None, None),
    conv_thr=(float | None, None),
    mixing_beta=(float | None, None),
    electron_maxstep=(int | None, None),
    use_vdw=(bool | None, None),
    vdw_method=(VdwMethod | None, None),
)
CapabilitiesDocument = create_model(
    "Capabilities",
    core_version=(str, ...),
    tasks=(tuple[_CapabilityTaskDocument, ...], ...),
    target_codes=(tuple[str, ...], ...),
    models=(tuple[_CapabilityModelDocument, ...], ...),
    pseudopotential_sets=(tuple[_CapabilityPseudopotentialSetDocument, ...], ...),
    default_intent=(_CapabilityIntentDocument, ...),
    default_hints=(_CapabilityHintsDocument, ...),
)
_SERIALIZED = ConfigDict(extra="forbid")
_SERIALIZED_MODELS: dict[type | TypeAliasType, Any] = {}


def _serialized_annotation(annotation: Any) -> Any:
    if annotation in _SERIALIZED_MODELS:
        return _SERIALIZED_MODELS[annotation]
    if isinstance(annotation, TypeAliasType):
        return _serialized_annotation(annotation.__value__)
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _serialized_model(annotation)

    origin = get_origin(annotation)
    if origin is None or origin is Literal:
        return annotation
    converted = tuple(_serialized_annotation(item) for item in get_args(annotation))
    if origin is tuple:
        if len(converted) == 2 and converted[1] is Ellipsis:
            return tuple[converted[0], ...]
        return tuple[converted]
    if origin is list:
        return list[converted[0]]
    if origin is dict:
        return dict[converted[0], converted[1]]
    if origin is types.UnionType:
        return reduce(or_, converted)
    return annotation


def _serialized_model(
    contract: type,
    *,
    name: str | None = None,
    exclude: frozenset[str] = frozenset(),
    overrides: dict[str, Any] | None = None,
) -> type[BaseModel]:
    hints = get_type_hints(contract)
    replacements = overrides or {}
    definitions: dict[str, Any] = {}
    for item in fields(contract):
        if item.name in exclude:
            continue
        annotation = _serialized_annotation(
            replacements.get(item.name, hints[item.name])
        )
        definitions[item.name] = (annotation, ...)
    document = create_model(
        name or contract.__name__, __config__=_SERIALIZED, **definitions
    )
    if not exclude and not replacements:
        _SERIALIZED_MODELS[contract] = document
    return document


SerializedIntentDocument = _serialized_model(
    CalculationIntent,
    name="SerializedCalculationIntent",
)
SerializedHintsDocument = _serialized_model(
    CalculationHints,
    name="SerializedCalculationHints",
)
SerializedModelDocument = _serialized_model(
    ModelSpec,
    name="SerializedModel",
    exclude=frozenset({"location", "licence_text"}),
)
_SERIALIZED_MODELS[ModelSpec] = SerializedModelDocument
SerializedPseudoMetadataDocument = _serialized_model(
    PseudoMetadata,
    name="SerializedPseudoMetadata",
    exclude=frozenset({"filepath", "pseudo_info"}),
)
_SERIALIZED_MODELS[PseudoMetadata] = SerializedPseudoMetadataDocument
SerializedPseudopotentialDocument = _serialized_model(
    PseudopotentialSelection,
    name="SerializedPseudopotentialSelection",
    exclude=frozenset({"filepath"}),
)
_SERIALIZED_MODELS[PseudopotentialSelection] = SerializedPseudopotentialDocument

GeneratedArtifactSourceDocument = create_model(
    "GeneratedArtifactSource",
    __config__=_SERIALIZED,
    kind=(Literal["generated"], ...),
    identity=(str, ...),
)
InstalledArtifactSourceDocument = create_model(
    "InstalledArtifactSource",
    __config__=_SERIALIZED,
    kind=(Literal["installed"], ...),
    asset_id=(str, ...),
    asset_version=(str, ...),
    preparation_fingerprint=(str, ...),
    path=(str, ...),
)
ArtifactSourceDocument = (
    GeneratedArtifactSourceDocument | InstalledArtifactSourceDocument
)
ProvenanceDocument = _serialized_model(Provenance)
_SmearingAdviceDocument = create_model(
    "SmearingAdvice",
    __config__=_SERIALIZED,
    smearing_type=(str | None, ...),
    width_ry=(float | None, ...),
    provenance=(ProvenanceDocument, ...),
)
_MagnetismAdviceDocument = create_model(
    "MagnetismAdvice",
    __config__=_SERIALIZED,
    spin_polarized=(bool, ...),
    magnetic_elements=(tuple[str, ...], ...),
    provenance=(ProvenanceDocument, ...),
)
_SpinOrbitAdviceDocument = create_model(
    "SpinOrbitAdvice",
    __config__=_SERIALIZED,
    enabled=(bool, ...),
    consider=(bool, ...),
    heavy_elements=(tuple[str, ...], ...),
    provenance=(ProvenanceDocument, ...),
)
_PseudopotentialRequirementsDocument = create_model(
    "PseudopotentialRequirements",
    __config__=_SERIALIZED,
    functional=(str, ...),
    accuracy=(PseudoAccuracy, ...),
    pseudo_type=(PseudoType | None, ...),
    relativistic=(RelativisticTreatment, ...),
    provenance=(ProvenanceDocument, ...),
)
_ConvergenceAdviceDocument = create_model(
    "ConvergenceAdvice",
    __config__=_SERIALIZED,
    conv_thr=(float, ...),
    provenance=(ProvenanceDocument, ...),
    mixing_beta=(float, ...),
    electron_maxstep=(int, ...),
)
_VdwAdviceDocument = create_model(
    "VdwAdvice",
    __config__=_SERIALIZED,
    use_vdw=(bool, ...),
    method=(VdwMethod | None, ...),
    provenance=(ProvenanceDocument, ...),
)
ParameterAdviceDocument = create_model(
    "ParameterAdvice",
    __config__=_SERIALIZED,
    smearing=(_SmearingAdviceDocument, ...),
    magnetism=(_MagnetismAdviceDocument, ...),
    spin_orbit=(_SpinOrbitAdviceDocument, ...),
    pseudopotential_requirements=(_PseudopotentialRequirementsDocument, ...),
    convergence=(_ConvergenceAdviceDocument, ...),
    vdw=(_VdwAdviceDocument, ...),
)
StructureAnalysisRecordDocument = create_model(
    "StructureAnalysisRecord",
    __config__=_SERIALIZED,
    formula=(str, ...),
    reduced_formula=(str, ...),
    site_count=(int, ...),
    elements=(tuple[str, ...], ...),
    contains_transition_metals=(bool, ...),
    contains_lanthanides=(bool, ...),
    contains_actinides=(bool, ...),
    contains_heavy_elements=(bool, ...),
    magnetic_elements=(tuple[str, ...], ...),
    heavy_elements=(tuple[str, ...], ...),
    disorder_warnings=(tuple[str, ...], ...),
    disordered_site_count=(int, ...),
    space_group_symbol=(str | int | None, ...),
    space_group_number=(str | int | None, ...),
    crystal_system=(str | int | None, ...),
    dimensionality=(Dimensionality, ...),
    low_dimensional=(bool, ...),
    electronic_character=(ElectronicCharacter, ...),
    electronic_character_source=(str, ...),
    electronic_character_confidence=(float | None, ...),
    analysis_warnings=(tuple[str, ...], ...),
)
_SERIALIZED_MODELS[ParameterAdvice] = ParameterAdviceDocument
_SERIALIZED_MODELS[StructureAnalysisRecord] = StructureAnalysisRecordDocument
SerializedInputArtifactDocument = create_model(
    "SerializedInputArtifact",
    __config__=_SERIALIZED,
    path=(str, ...),
    role=(str, ...),
    sha256=(str, ...),
    size_bytes=(int, ...),
    source=(ArtifactSourceDocument, ...),
    media_type=(str | None, ...),
    provenance=(ProvenanceDocument | None, ...),
)
RuntimeAssetFileDocument = create_model(
    "RuntimeAssetFile",
    __config__=_SERIALIZED,
    path=(str, ...),
    role=(str, ...),
    sha256=(str, ...),
    size_bytes=(int, ...),
)
SerializedRuntimeAssetDocument = create_model(
    "SerializedRuntimeAsset",
    __config__=_SERIALIZED,
    id=(str, ...),
    version=(str, ...),
    role=(str, ...),
    preparation_fingerprint=(str, ...),
    model=(SerializedModelDocument, ...),
    files=(list[RuntimeAssetFileDocument], ...),
)
SerializedRuntimeDocument = create_model(
    "SerializedRuntime",
    __config__=_SERIALIZED,
    core_version=(str, ...),
    models=(list[SerializedModelDocument], ...),
    assets=(list[SerializedRuntimeAssetDocument], ...),
)
PseudopotentialSetDocument = create_model(
    "PseudopotentialSetIdentity",
    __config__=_SERIALIZED,
    id=(str, ...),
    version=(str | None, ...),
    provider=(str, ...),
    functional=(str, ...),
    accuracy=(str, ...),
    relativistic=(str, ...),
    licence=(str, ...),
    citation=(str, ...),
    policy=(JsonDict, ...),
)
PublicationDocument = create_model(
    "Publication",
    __config__=_SERIALIZED,
    kind=(Literal["directory", "archive"], ...),
    path=(str, ...),
    files=(list[str], ...),
    manifest_sha256=(str, ...),
    output_sha256=(str | None, ...),
)
DftInputDataDocument = create_model(
    "DftInputData",
    __config__=_SERIALIZED,
    artifacts=(list[SerializedInputArtifactDocument], ...),
    pseudopotential_set=(PseudopotentialSetDocument, ...),
    runtime=(SerializedRuntimeDocument, ...),
    citations=(list[str], ...),
    manifest=(JsonDict, ...),
    schema_version=(Literal[1], ...),
)
_SERIALIZED_MODELS[DftInputData] = DftInputDataDocument

LocalPseudoRootDocument = create_model(
    "LocalPseudoRoot",
    __config__=_SERIALIZED,
    kind=(Literal["local_root"], ...),
)
SerializedCalculationDraftDocument = create_model(
    "SerializedCalculationDraft",
    __config__=_SERIALIZED,
    structure=(StructureInspectionDocument, ...),
    intent=(SerializedIntentDocument, ...),
    hints=(SerializedHintsDocument, ...),
    pseudo_metadata=(list[SerializedPseudoMetadataDocument] | None, ...),
    pseudo_root=(LocalPseudoRootDocument | None, ...),
    pseudo_table=(str | None, ...),
    kmesh_model=(SerializedModelDocument | None, ...),
)


def computation_result_document(
    tasks: tuple[dict[str, Any], ...],
) -> type[BaseModel]:
    advertised_ids = dict.fromkeys(
        record_id
        for task in tasks
        for record_id in (
            *task["selectable_record_ids"],
            *(
                output_id
                for preset in task["presets"]
                for output_id in preset["output_record_ids"]
            ),
        )
    )
    registered_types = record_types_by_id()
    records_document = create_model(
        "Records",
        __config__=_SERIALIZED,
        **{
            record_id: (_serialized_annotation(registered_types[record_id]), None)
            for record_id in advertised_ids
        },
    )
    return create_model(
        "ComputationResult",
        __config__=_STRICT,
        schema_version=(Literal[1], ...),
        draft=(SerializedCalculationDraftDocument, ...),
        task=(str, ...),
        task_revision=(str, ...),
        selection=(SelectionDocument, ...),
        records=(records_document, ...),
        warnings=(list[str], ...),
        publication=(PublicationDocument | None, ...),
    )


def prepared_computation_document(
    tasks: tuple[dict[str, Any], ...],
) -> type[BaseModel]:
    return create_model(
        "PreparedComputation",
        __config__=_STRICT,
        result=(computation_result_document(tasks), ...),
        archive=(bytes | None, None),
    )


ErrorDocument = create_model(
    "Error",
    __config__=_STRICT,
    kind=(str, ...),
    message=(str, ...),
    retryable=(bool | None, None),
    details=(dict[str, JsonValue] | None, None),
    asset_id=(str | None, None),
    version=(str | None, None),
    reason=(str | None, None),
)
ErrorResponseDocument = create_model(
    "ErrorResponse", __config__=_STRICT, error=(ErrorDocument, ...)
)
