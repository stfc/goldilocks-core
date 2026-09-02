from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as package_version

from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.registry import available_codes
from goldilocks_core.ml.model_registry import registered_models
from goldilocks_core.pseudo.registry import load_tables
from goldilocks_core.runtime.dispatch import Dispatcher
from goldilocks_core.runtime.graph import CalculationTaskCapability
from goldilocks_core.runtime.models import Runtime


@dataclass(frozen=True, slots=True)
class ModelCapability:
    id: str
    name: str
    version: str
    role: str
    model_type: str
    target: str
    feature_set: str
    source: str
    revision: str | None


@dataclass(frozen=True, slots=True)
class PseudopotentialSetCapability:
    id: str
    version: str
    provider: str
    upstream_name: str
    functional: str
    accuracy: str
    relativistic_treatment: str
    supported_elements: tuple[str, ...]
    licence: str
    citation: str
    default: bool


@dataclass(frozen=True, slots=True)
class Capabilities:
    core_version: str
    tasks: tuple[CalculationTaskCapability, ...]
    target_codes: tuple[str, ...]
    models: tuple[ModelCapability, ...]
    pseudopotential_sets: tuple[PseudopotentialSetCapability, ...]
    default_intent: CalculationIntent
    default_hints: CalculationHints


def build_capabilities(dispatcher: Dispatcher, runtime: Runtime) -> Capabilities:
    models = registered_models(runtime.model_registry_path)
    pseudopotential_sets = load_tables(runtime.pseudo_registry_path)
    return Capabilities(
        core_version=package_version("goldilocks-core"),
        tasks=tuple(sorted(dispatcher.describe_tasks(), key=lambda task: task.id)),
        target_codes=tuple(sorted(available_codes())),
        models=tuple(
            ModelCapability(
                id=registration.id,
                name=registration.spec.name,
                version=registration.spec.version,
                role=registration.role,
                model_type=registration.spec.model_type,
                target=registration.spec.target,
                feature_set=registration.spec.feature_set,
                source=registration.spec.source,
                revision=registration.spec.revision,
            )
            for registration in sorted(models, key=lambda model: model.id)
        ),
        pseudopotential_sets=tuple(
            PseudopotentialSetCapability(
                id=table.id,
                version=table.version,
                provider=table.provider,
                upstream_name=table.upstream_table,
                functional=table.functional,
                accuracy=table.accuracy,
                relativistic_treatment=table.relativistic,
                supported_elements=tuple(sorted(table.elements)),
                licence=table.licence,
                citation=table.citation,
                default=table.default,
            )
            for table in sorted(pseudopotential_sets.values(), key=lambda item: item.id)
        ),
        default_intent=CalculationIntent(),
        default_hints=CalculationHints(),
    )
